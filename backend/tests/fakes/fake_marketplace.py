"""A stateful in-memory implementation of MARKETPLACE.md.

This is the reference implementation the instance side is tested against, and it
unblocks everything before the real central server exists. It is deliberately a
real FastAPI app rather than a bag of canned responses: the client's retry,
error-envelope and cursor handling only mean something against a server that
actually runs a state machine.

The transport bridge is sync because ``MarketplaceClient`` wraps ``httpx.Client``
— ``httpx.ASGITransport`` is async-only, so requests are forwarded through a
Starlette ``TestClient`` (itself an ASGI transport plus a blocking portal).
"""

from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _money(value) -> str:
    """Money and quantities cross the wire as decimal strings — float
    round-tripping silently corrupts tax arithmetic (contract §1)."""
    return str(Decimal(str(value)))


class MarketplaceHTTPError(Exception):
    def __init__(self, status: int, error: str, **extra) -> None:
        super().__init__(error)
        self.status = status
        self.error = error
        self.extra = extra


class FakeMarketplace:
    def __init__(self, *, auto_approve: bool = True, order_ttl_hours: int = 168) -> None:
        self.auto_approve = auto_approve
        self.order_ttl_hours = order_ttl_hours

        self.sellers: dict[str, dict] = {}
        self.keys: dict[str, str] = {}
        self.listings: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.events: dict[str, list[dict]] = defaultdict(list)
        self._seq: dict[str, int] = defaultdict(int)
        # Everything at or below this seq is "expired" for that subscriber, which
        # is what makes a stale cursor answer 409 cursor_too_old.
        self.retention_floor: dict[str, int] = defaultdict(int)
        self.idempotency: dict[tuple[str, str], dict] = {}

        self._counter = 0
        self.app = self._build_app()
        self._test_client = TestClient(self.app)

    # ------------------------------------------------------------------
    # Transport seam
    # ------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._forward)

    def _forward(self, request: httpx.Request) -> httpx.Response:
        response = self._test_client.request(
            request.method,
            str(request.url),
            content=request.content or None,
            headers={
                k: v
                for k, v in request.headers.items()
                if k.lower() not in ("host", "content-length")
            },
        )
        return httpx.Response(
            status_code=response.status_code,
            content=response.content,
            headers={"content-type": response.headers.get("content-type", "application/json")},
        )

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter:06d}"

    def seller_by_gstin(self, gstin: str) -> dict | None:
        for seller in self.sellers.values():
            if seller["gstin"] == gstin:
                return seller
        return None

    def approve(self, seller_id: str) -> None:
        seller = self.sellers[seller_id]
        seller["status"] = "active"
        self.emit(seller_id, "seller.status_changed", None, {"status": "active"})

    def suspend(self, seller_id: str, reason: str = "policy") -> None:
        self.sellers[seller_id]["status"] = "suspended"
        self.emit(
            seller_id, "seller.status_changed", None, {"status": "suspended", "reason": reason}
        )

    def emit(self, seller_id: str, event_type: str, order_id: str | None, data: dict) -> dict:
        """Append to a subscriber's outbox. seq is per-subscriber and monotonic —
        the single server-side invariant the client's in-order application rests on."""
        self._seq[seller_id] += 1
        event = {
            "event_id": self._next_id("evt"),
            "seq": self._seq[seller_id],
            "type": event_type,
            "occurred_at": _now(),
            "order_id": order_id,
            "data": data,
        }
        self.events[seller_id].append(event)
        return event

    def redeliver_last_event(self, seller_id: str) -> dict:
        """Append the newest event again with the SAME event_id but a fresh seq —
        exactly what an at-least-once feed does after a partial failure."""
        original = self.events[seller_id][-1]
        self._seq[seller_id] += 1
        duplicate = dict(original)
        duplicate["seq"] = self._seq[seller_id]
        self.events[seller_id].append(duplicate)
        return duplicate

    def inject_out_of_order_event(
        self, seller_id: str, event_type: str, order_id: str, data: dict | None = None
    ) -> dict:
        """Deliver a transition that is unreachable from the order's current
        state, e.g. order.accepted after order.cancelled."""
        order = self.orders.get(order_id, {})
        payload = data if data is not None else self._order_snapshot(order, viewer="buyer")
        return self.emit(seller_id, event_type, order_id, payload)

    def force_cursor_too_old(self, seller_id: str, resync_from: int | None = None) -> None:
        """Make the next /events call with a stale cursor answer 409."""
        floor = resync_from if resync_from is not None else self._seq[seller_id]
        self.retention_floor[seller_id] = floor

    def set_listing_quantity(self, listing_id: str, quantity) -> None:
        self.listings[listing_id]["available_quantity"] = _money(quantity)

    def tamper_posted_event(self, seller_id: str, **line_overrides) -> dict:
        """Rewrite the newest order.posted payload as a compromised server would.

        Used to prove the divergence check actually refuses, rather than trusting
        whatever the central server says.
        """
        for event in reversed(self.events[seller_id]):
            if event["type"] == "order.posted":
                for line in event["data"]["lines"]:
                    line.update(line_overrides)
                return event
        raise AssertionError("no order.posted event to tamper with")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _seller_for_key(self, authorization: str | None) -> dict:
        if not authorization or not authorization.startswith("Bearer "):
            raise MarketplaceHTTPError(401, "unauthorized")
        seller_id = self.keys.get(authorization.split(" ", 1)[1])
        if seller_id is None:
            raise MarketplaceHTTPError(401, "unauthorized")
        return self.sellers[seller_id]

    @staticmethod
    def _require_active(seller: dict) -> None:
        if seller["status"] != "active":
            raise MarketplaceHTTPError(403, "seller_not_approved")

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def _party(self, seller_id: str) -> dict:
        seller = self.sellers[seller_id]
        return {
            "seller_id": seller["seller_id"],
            "legal_name": seller["legal_name"],
            "gstin": seller["gstin"],
            "state_code": seller["state_code"],
            "address": seller["address"],
            "contact_phone": seller["contact_phone"],
            "contact_email": seller["contact_email"],
            "verified": False,
        }

    def _order_snapshot(self, order: dict, *, viewer: str) -> dict:
        counterparty = order["buyer_id"] if viewer == "seller" else order["seller_id"]
        snapshot = {
            "order_id": order["order_id"],
            "state": order["state"],
            "order_type": "buy_now",
            "listing_id": order["listing_id"],
            "currency_code": "INR",
            "quantity": order["quantity"],
            "unit_price": order["unit_price"],
            "total_amount": order["total_amount"],
            "created_at": order["created_at"],
            "expires_at": order["expires_at"],
            "accepted_at": order.get("accepted_at"),
            "closed_at": order.get("closed_at"),
            "reject_reason": order.get("reject_reason"),
            "reject_note": order.get("reject_note"),
            "buyer_note": order.get("buyer_note"),
            "delivery_address": order.get("delivery_address"),
            "lines": order["lines"],
        }
        snapshot["buyer" if viewer == "seller" else "seller"] = self._party(counterparty)
        return snapshot

    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------

    def _build_app(self) -> FastAPI:  # noqa: C901 — one contract, one place
        app = FastAPI()
        fake = self

        @app.exception_handler(MarketplaceHTTPError)
        async def _handle(_request: Request, exc: MarketplaceHTTPError):
            body = {"error": exc.error, "detail": exc.error, "request_id": "req_fake"}
            body.update(exc.extra)
            return JSONResponse(status_code=exc.status, content=body)

        # -- discovery ------------------------------------------------

        @app.get("/v1/health")
        async def health():
            return {"status": "ok"}

        @app.get("/v1/meta")
        async def meta():
            return {
                "marketplace_name": "Fake Marketplace",
                "min_client_version": "0.1.0",
                "terms_url": "https://example.test/terms",
                "registration_open": True,
                "requires_approval": True,
                "order_ttl_hours": fake.order_ttl_hours,
                "event_retention_days": 90,
            }

        # -- registration ---------------------------------------------

        @app.post("/v1/sellers/register", status_code=201)
        async def register(payload: dict):
            gstin = payload.get("gstin")
            if not gstin or len(gstin) != 15:
                raise MarketplaceHTTPError(422, "invalid_gstin")
            if fake.seller_by_gstin(gstin):
                raise MarketplaceHTTPError(409, "gstin_already_claimed")

            seller_id = fake._next_id("sel")
            api_key = "mk_live_" + secrets.token_hex(32)
            fake.sellers[seller_id] = {
                "seller_id": seller_id,
                "gstin": gstin,
                "legal_name": payload.get("legal_name") or gstin,
                "address": payload.get("address") or "",
                "state_code": payload.get("state_code") or gstin[:2],
                "contact_email": payload.get("contact_email"),
                "contact_phone": payload.get("contact_phone"),
                "instance_uuid": payload.get("instance_id"),
                "status": "pending_approval",
            }
            fake.keys[api_key] = seller_id
            if fake.auto_approve:
                # The approval arrives as an event, so the instance flips to
                # connected on its next sync without re-registering.
                fake.approve(seller_id)
            return {
                "seller_id": seller_id,
                "api_key": api_key,
                "status": "pending_approval",
            }

        @app.get("/v1/sellers/me")
        async def get_me(authorization: str | None = Header(default=None)):
            seller = fake._seller_for_key(authorization)
            return {
                **fake._party(seller["seller_id"]),
                "status": seller["status"],
                "listing_count": sum(
                    1 for l in fake.listings.values() if l["seller_id"] == seller["seller_id"]
                ),
                "open_order_count": sum(
                    1
                    for o in fake.orders.values()
                    if o["state"] == "pending"
                    and seller["seller_id"] in (o["seller_id"], o["buyer_id"])
                ),
            }

        @app.patch("/v1/sellers/me")
        async def patch_me(payload: dict, authorization: str | None = Header(default=None)):
            seller = fake._seller_for_key(authorization)
            for field in ("legal_name", "address", "contact_email", "contact_phone"):
                if payload.get(field) is not None:
                    seller[field] = payload[field]
            return fake._party(seller["seller_id"])

        @app.post("/v1/sellers/me/rotate-key")
        async def rotate(authorization: str | None = Header(default=None)):
            seller = fake._seller_for_key(authorization)
            api_key = "mk_live_" + secrets.token_hex(32)
            fake.keys[api_key] = seller["seller_id"]
            return {"api_key": api_key}

        @app.delete("/v1/sellers/me", status_code=204)
        async def delete_me(authorization: str | None = Header(default=None)):
            seller = fake._seller_for_key(authorization)
            seller["status"] = "closed"
            for listing in fake.listings.values():
                if listing["seller_id"] == seller["seller_id"]:
                    listing["status"] = "withdrawn"
            return None

        # -- listings --------------------------------------------------

        @app.post("/v1/listings", status_code=201)
        async def create_listing(payload: dict, authorization: str | None = Header(default=None)):
            seller = fake._seller_for_key(authorization)
            fake._require_active(seller)
            listing_id = fake._next_id("lst")
            listing = {
                "listing_id": listing_id,
                "seller_id": seller["seller_id"],
                "title": payload.get("title"),
                "description": payload.get("description"),
                "asking_price": _money(payload.get("asking_price") or 0),
                "currency_code": payload.get("currency_code") or "INR",
                "gst_rate": _money(payload.get("gst_rate") or 0),
                "hsn_sac": payload.get("hsn_sac"),
                "unit": payload.get("unit") or "Pieces",
                "allow_decimal": bool(payload.get("allow_decimal")),
                "min_order_quantity": payload.get("min_order_quantity"),
                "max_order_quantity": payload.get("max_order_quantity"),
                "available_quantity": _money(payload.get("available_quantity") or 0),
                "available_quantity_as_of": _now(),
                "reserved_quantity": "0",
                "status": "active",
                "listing_type": payload.get("listing_type") or "buy_now",
                "external_ref": payload.get("external_ref"),
            }
            fake.listings[listing_id] = listing
            return listing

        @app.get("/v1/listings/mine")
        async def my_listings(
            status: str | None = None, authorization: str | None = Header(default=None)
        ):
            seller = fake._seller_for_key(authorization)
            items = [
                l
                for l in fake.listings.values()
                if l["seller_id"] == seller["seller_id"]
                and (status is None or l["status"] == status)
            ]
            return {"items": items, "total_estimate": len(items)}

        @app.get("/v1/listings")
        async def browse(
            request: Request,
            q: str | None = None,
            exclude_own: bool = False,
            authorization: str | None = Header(default=None),
        ):
            seller = fake._seller_for_key(authorization)
            fake._require_active(seller)
            items = []
            for listing in fake.listings.values():
                if listing["status"] != "active":
                    continue
                if exclude_own and listing["seller_id"] == seller["seller_id"]:
                    continue
                if q and q.lower() not in (listing["title"] or "").lower():
                    continue
                items.append({**listing, "seller": fake._party(listing["seller_id"])})
            return {"items": items, "next_cursor": None, "total_estimate": len(items)}

        @app.get("/v1/listings/{listing_id}")
        async def get_listing(listing_id: str, authorization: str | None = Header(default=None)):
            fake._seller_for_key(authorization)
            listing = fake.listings.get(listing_id)
            if listing is None:
                raise MarketplaceHTTPError(404, "listing_not_found")
            return {**listing, "seller": fake._party(listing["seller_id"])}

        @app.patch("/v1/listings/{listing_id}")
        async def patch_listing(
            listing_id: str, payload: dict, authorization: str | None = Header(default=None)
        ):
            seller = fake._seller_for_key(authorization)
            listing = fake.listings.get(listing_id)
            if listing is None or listing["seller_id"] != seller["seller_id"]:
                raise MarketplaceHTTPError(404, "listing_not_found")
            listing.update({k: v for k, v in payload.items() if v is not None})
            listing["available_quantity_as_of"] = _now()
            return listing

        @app.delete("/v1/listings/{listing_id}", status_code=204)
        async def delete_listing(
            listing_id: str, authorization: str | None = Header(default=None)
        ):
            seller = fake._seller_for_key(authorization)
            listing = fake.listings.get(listing_id)
            if listing is None or listing["seller_id"] != seller["seller_id"]:
                raise MarketplaceHTTPError(404, "listing_not_found")
            listing["status"] = "withdrawn"
            return None

        # -- orders ----------------------------------------------------

        def _idempotent(seller_id: str, key: str | None):
            if key is None:
                return None
            return fake.idempotency.get((seller_id, key))

        @app.post("/v1/orders", status_code=201)
        async def create_order(
            payload: dict,
            authorization: str | None = Header(default=None),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ):
            buyer = fake._seller_for_key(authorization)
            fake._require_active(buyer)
            stored = _idempotent(buyer["seller_id"], idempotency_key)
            if stored is not None:
                return stored

            listing = fake.listings.get(payload.get("listing_id"))
            if listing is None or listing["status"] != "active":
                raise MarketplaceHTTPError(409, "listing_not_active")
            if listing["seller_id"] == buyer["seller_id"]:
                raise MarketplaceHTTPError(409, "cannot_order_own_listing")

            quantity = Decimal(str(payload.get("quantity") or 0))
            available = Decimal(listing["available_quantity"]) - Decimal(
                listing["reserved_quantity"]
            )
            if quantity > available:
                raise MarketplaceHTTPError(
                    409, "insufficient_advertised_quantity", available=str(available)
                )
            # Soft reservation only — the seller's instance holds the real stock.
            listing["reserved_quantity"] = _money(
                Decimal(listing["reserved_quantity"]) + quantity
            )

            unit_price = Decimal(listing["asking_price"])
            order_id = fake._next_id("ord")
            order = {
                "order_id": order_id,
                "listing_id": listing["listing_id"],
                "seller_id": listing["seller_id"],
                "buyer_id": buyer["seller_id"],
                "state": "pending",
                "quantity": _money(quantity),
                "unit_price": _money(unit_price),
                "total_amount": _money(unit_price * quantity),
                "created_at": _now(),
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=fake.order_ttl_hours)
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "buyer_note": payload.get("buyer_note"),
                "delivery_address": payload.get("delivery_address"),
                "lines": [
                    {
                        "line_no": 1,
                        "listing_id": listing["listing_id"],
                        "title": listing["title"],
                        "quantity": _money(quantity),
                        "unit": listing["unit"],
                        "unit_price": _money(unit_price),
                        "gst_rate": listing["gst_rate"],
                        "hsn_sac": listing["hsn_sac"],
                    }
                ],
            }
            fake.orders[order_id] = order
            fake.emit(
                listing["seller_id"],
                "order.created",
                order_id,
                fake._order_snapshot(order, viewer="seller"),
            )
            response = fake._order_snapshot(order, viewer="buyer")
            if idempotency_key:
                fake.idempotency[(buyer["seller_id"], idempotency_key)] = response
            return response

        @app.get("/v1/orders")
        async def list_orders(
            role: str = "seller",
            state: str | None = None,
            authorization: str | None = Header(default=None),
        ):
            seller = fake._seller_for_key(authorization)
            key = "seller_id" if role == "seller" else "buyer_id"
            viewer = "seller" if role == "seller" else "buyer"
            items = [
                fake._order_snapshot(o, viewer=viewer)
                for o in fake.orders.values()
                if o[key] == seller["seller_id"] and (state is None or o["state"] == state)
            ]
            return {"items": items, "total_estimate": len(items)}

        @app.get("/v1/orders/{order_id}")
        async def get_order(order_id: str, authorization: str | None = Header(default=None)):
            seller = fake._seller_for_key(authorization)
            order = fake.orders.get(order_id)
            if order is None:
                raise MarketplaceHTTPError(404, "order_not_found")
            viewer = "seller" if order["seller_id"] == seller["seller_id"] else "buyer"
            return fake._order_snapshot(order, viewer=viewer)

        def _require_order(order_id: str, seller: dict, role: str) -> dict:
            order = fake.orders.get(order_id)
            if order is None:
                raise MarketplaceHTTPError(404, "order_not_found")
            if order[f"{role}_id"] != seller["seller_id"]:
                raise MarketplaceHTTPError(403, "forbidden")
            return order

        @app.post("/v1/orders/{order_id}/accept")
        async def accept_order(
            order_id: str,
            authorization: str | None = Header(default=None),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ):
            seller = fake._seller_for_key(authorization)
            stored = _idempotent(seller["seller_id"], idempotency_key)
            if stored is not None:
                return stored
            order = _require_order(order_id, seller, "seller")
            if order["state"] != "pending":
                raise MarketplaceHTTPError(
                    409, "invalid_state_transition", state=order["state"]
                )
            order["state"] = "accepted"
            order["accepted_at"] = _now()
            fake.emit(
                order["buyer_id"],
                "order.accepted",
                order_id,
                fake._order_snapshot(order, viewer="buyer"),
            )
            response = {"state": "accepted", "accepted_at": order["accepted_at"]}
            if idempotency_key:
                fake.idempotency[(seller["seller_id"], idempotency_key)] = response
            return response

        @app.post("/v1/orders/{order_id}/reject")
        async def reject_order(
            order_id: str, payload: dict, authorization: str | None = Header(default=None)
        ):
            seller = fake._seller_for_key(authorization)
            order = _require_order(order_id, seller, "seller")
            if order["state"] != "pending":
                raise MarketplaceHTTPError(
                    409, "invalid_state_transition", state=order["state"]
                )
            order["state"] = "rejected"
            order["reject_reason"] = payload.get("reason")
            order["reject_note"] = payload.get("note")
            order["closed_at"] = _now()
            listing = fake.listings.get(order["listing_id"])
            if listing:
                listing["reserved_quantity"] = _money(
                    Decimal(listing["reserved_quantity"]) - Decimal(order["quantity"])
                )
            fake.emit(
                order["buyer_id"],
                "order.rejected",
                order_id,
                {
                    **fake._order_snapshot(order, viewer="buyer"),
                    "reason": order["reject_reason"],
                    "note": order["reject_note"],
                },
            )
            return {"state": "rejected"}

        @app.post("/v1/orders/{order_id}/cancel")
        async def cancel_order(order_id: str, authorization: str | None = Header(default=None)):
            buyer = fake._seller_for_key(authorization)
            order = _require_order(order_id, buyer, "buyer")
            if order["state"] != "pending":
                raise MarketplaceHTTPError(
                    409, "invalid_state_transition", state=order["state"]
                )
            order["state"] = "cancelled"
            order["closed_at"] = _now()
            fake.emit(
                order["seller_id"],
                "order.cancelled",
                order_id,
                fake._order_snapshot(order, viewer="seller"),
            )
            return {"state": "cancelled"}

        @app.post("/v1/orders/{order_id}/posting")
        async def report_posting(
            order_id: str,
            payload: dict,
            authorization: str | None = Header(default=None),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ):
            seller = fake._seller_for_key(authorization)
            stored = _idempotent(seller["seller_id"], idempotency_key)
            if stored is not None:
                return stored
            order = _require_order(order_id, seller, "seller")
            if order["state"] != "accepted":
                raise MarketplaceHTTPError(
                    409, "invalid_state_transition", state=order["state"]
                )
            order["state"] = "posted"
            order["seller_invoice_number"] = payload.get("invoice_number")
            order["seller_invoice_date"] = payload.get("invoice_date")
            # This event is what unlocks the buyer's auto-post: the buyer must
            # never post off order.accepted alone.
            fake.emit(
                order["buyer_id"],
                "order.posted",
                order_id,
                {
                    **fake._order_snapshot(order, viewer="buyer"),
                    "invoice_number": payload.get("invoice_number"),
                    "invoice_date": payload.get("invoice_date"),
                    "seller_gstin": payload.get("seller_gstin"),
                    "taxable_amount": payload.get("taxable_amount"),
                    "tax_amount": payload.get("tax_amount"),
                    "total_amount": payload.get("total_amount"),
                    "lines": payload.get("lines") or order["lines"],
                },
            )
            response = {"state": "posted"}
            if idempotency_key:
                fake.idempotency[(seller["seller_id"], idempotency_key)] = response
            return response

        @app.post("/v1/orders/{order_id}/buyer-posting")
        async def report_buyer_posting(
            order_id: str, payload: dict, authorization: str | None = Header(default=None)
        ):
            buyer = fake._seller_for_key(authorization)
            order = _require_order(order_id, buyer, "buyer")
            order["buyer_invoice_number"] = payload.get("invoice_number")
            fake.emit(
                order["seller_id"],
                "order.buyer_posted",
                order_id,
                {
                    "order_id": order_id,
                    "invoice_number": payload.get("invoice_number"),
                    "invoice_date": payload.get("invoice_date"),
                },
            )
            return {"ok": True}

        # -- events ----------------------------------------------------

        @app.get("/v1/events")
        async def get_events(
            since: int = 0, limit: int = 200, authorization: str | None = Header(default=None)
        ):
            seller = fake._seller_for_key(authorization)
            seller_id = seller["seller_id"]
            floor = fake.retention_floor[seller_id]
            if since < floor:
                raise MarketplaceHTTPError(409, "cursor_too_old", resync_from=floor)

            pending = [e for e in fake.events[seller_id] if e["seq"] > since]
            page = pending[:limit]
            return {
                "events": page,
                "next_since": page[-1]["seq"] if page else since,
                "has_more": len(pending) > len(page),
                "retention_until_seq": floor,
            }

        return app
