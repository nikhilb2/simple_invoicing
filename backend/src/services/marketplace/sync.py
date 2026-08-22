"""Pull-based event drain.

The central server can never reach an instance — self-hosted boxes sit on
localhost or behind NAT — so delivery is a cursor-ordered feed the instance
drains itself.

The load-bearing invariant of this module: **event ingestion never creates
invoices.** Applying an event only advances order state. Posting is a separate
reconciler pass (posting.py) keyed off ``posting_state``. If the process dies
between the two, the cursor is committed but the order is still ``pending``, so
the next drain retries the post rather than losing or duplicating it.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.marketplace import (
    MarketplaceConnection,
    MarketplaceListing,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplaceProcessedEvent,
)
from src.schemas.marketplace import SyncResultOut
from src.services.marketplace.client import (
    MarketplaceAuthError,
    MarketplaceConflict,
    MarketplaceError,
    client_for_connection,
)
from src.services.marketplace import posting as posting_service

logger = logging.getLogger(__name__)

SYNC_LOCK_SECONDS = 120
MAX_PAGES = 10
PAGE_SIZE = 200
DRAIN_BUDGET_SECONDS = 20.0

# Which side of the trade we are on when a given event type arrives. order.expired
# goes to both sides, so it is resolved from the row we already hold.
_EVENT_SIDE = {
    "order.created": "sell",
    "order.cancelled": "sell",
    "order.buyer_posted": "sell",
    "order.accepted": "buy",
    "order.rejected": "buy",
    "order.posted": "buy",
}

# The state-machine guard. An unreachable transition is recorded as `ignored`
# rather than applied — a redelivered order.accepted must not resurrect an order
# the buyer already cancelled.
_ALLOWED_FROM = {
    "order.cancelled": {"pending"},
    "order.expired": {"pending", "accepted"},
    "order.accepted": {"pending"},
    "order.rejected": {"pending"},
    # Never `pending`: the buyer must not post off order.accepted alone, and a
    # posted event for an order we never saw accepted is not trustworthy.
    "order.posted": {"accepted"},
}


def _dec(value) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text_value = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return None
    # Stored naive-UTC to match every other DateTime column in this schema.
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

def acquire_sync_lock(db: Session, connection: MarketplaceConnection) -> bool:
    """Claim the drain lock with a conditional UPDATE.

    Deliberately not ``pg_advisory_lock``: the test suite runs on SQLite, and a
    lock the tests cannot exercise is a lock nobody has verified.
    """
    now = datetime.utcnow()
    result = db.execute(
        text(
            """
            UPDATE marketplace_connections
               SET sync_lock_until = :lock_until
             WHERE company_id = :company_id
               AND (sync_lock_until IS NULL OR sync_lock_until < :now)
            """
        ),
        {
            "company_id": connection.company_id,
            "now": now,
            "lock_until": now + timedelta(seconds=SYNC_LOCK_SECONDS),
        },
    )
    acquired = result.rowcount == 1
    db.commit()
    return acquired


def release_sync_lock(db: Session, connection: MarketplaceConnection, error: str | None) -> None:
    db.execute(
        text(
            """
            UPDATE marketplace_connections
               SET sync_lock_until = NULL,
                   last_sync_at = :now,
                   last_sync_error = :error
             WHERE company_id = :company_id
            """
        ),
        {"company_id": connection.company_id, "now": datetime.utcnow(), "error": error},
    )
    db.commit()


# ---------------------------------------------------------------------------
# Order upsert
# ---------------------------------------------------------------------------

def _counterparty(data: dict, side: str) -> dict:
    if side == "sell":
        party = data.get("buyer") or data.get("counterparty") or {}
    else:
        party = data.get("seller") or data.get("counterparty") or {}
    return party if isinstance(party, dict) else {}


def upsert_order_from_snapshot(
    db: Session,
    connection: MarketplaceConnection,
    data: dict,
    side: str,
) -> MarketplaceOrder:
    """Create or refresh the local mirror of a remote order snapshot.

    Never touches ``posting_state`` — that belongs to the posting reconciler.
    """
    remote_order_id = str(data.get("order_id") or data.get("id") or "")
    order = (
        db.query(MarketplaceOrder)
        .filter(
            MarketplaceOrder.company_id == connection.company_id,
            MarketplaceOrder.remote_order_id == remote_order_id,
        )
        .first()
    )
    created = order is None
    if created:
        order = MarketplaceOrder(
            company_id=connection.company_id,
            side=side,
            remote_order_id=remote_order_id,
            posting_state="not_required",
        )
        db.add(order)

    order.order_type = data.get("order_type") or order.order_type or "buy_now"
    if data.get("state"):
        order.state = data["state"]
    party = _counterparty(data, order.side)
    order.counterparty_remote_id = party.get("seller_id") or party.get("buyer_id") or order.counterparty_remote_id
    order.counterparty_name = party.get("legal_name") or order.counterparty_name
    order.counterparty_gstin = party.get("gstin") or order.counterparty_gstin
    order.counterparty_address = party.get("address") or order.counterparty_address
    order.counterparty_phone = party.get("contact_phone") or order.counterparty_phone
    order.counterparty_email = party.get("contact_email") or order.counterparty_email
    order.currency_code = data.get("currency_code") or order.currency_code or "INR"
    if data.get("total_amount") is not None:
        order.remote_total_amount = _dec(data.get("total_amount"))
    order.order_placed_at = _parse_dt(data.get("created_at")) or order.order_placed_at or datetime.utcnow()
    order.expires_at = _parse_dt(data.get("expires_at")) or order.expires_at
    order.accepted_at = _parse_dt(data.get("accepted_at")) or order.accepted_at
    order.closed_at = _parse_dt(data.get("closed_at")) or order.closed_at
    order.reject_reason = data.get("reject_reason") or order.reject_reason
    order.reject_note = data.get("reject_note") or order.reject_note
    db.flush()

    lines = data.get("lines") or []
    # Lines are written ONCE, when the order first appears. The locally-held
    # lines are the reference the order.posted divergence check compares against,
    # so letting a later snapshot rewrite them would defeat the whole check.
    if lines and not order.items:
        for index, line in enumerate(lines, start=1):
            db.add(
                MarketplaceOrderItem(
                    order_id=order.id,
                    line_no=int(line.get("line_no") or index),
                    remote_listing_id=str(line.get("listing_id") or "") or None,
                    title=line.get("title"),
                    quantity=_dec(line.get("quantity")),
                    unit=line.get("unit"),
                    unit_price=_dec(line.get("unit_price")),
                    gst_rate=_dec(line.get("gst_rate")),
                    hsn_sac=line.get("hsn_sac"),
                )
            )
        db.flush()
        if not order.remote_listing_id:
            order.remote_listing_id = str(lines[0].get("listing_id") or "") or None
    elif data.get("listing_id"):
        order.remote_listing_id = str(data["listing_id"])
    db.flush()
    return order


# ---------------------------------------------------------------------------
# Event application
# ---------------------------------------------------------------------------

def apply_event(
    db: Session, connection: MarketplaceConnection, event: dict
) -> tuple[str, str | None]:
    """Apply one event. Returns ``(result, error)`` with result in
    applied|ignored|error. Mutates orders/listings/connection ONLY."""
    event_type = event.get("type") or ""
    data = event.get("data") or {}
    seq = int(event.get("seq") or 0)

    if event_type == "seller.status_changed":
        status = data.get("status")
        mapping = {
            "active": "connected",
            "pending_approval": "pending_approval",
            "suspended": "suspended",
            "rejected": "disconnected",
            "closed": "disconnected",
        }
        if status in mapping:
            connection.status = mapping[status]
            return "applied", None
        return "ignored", f"unknown seller status {status}"

    if event_type == "listing.moderated":
        listing = (
            db.query(MarketplaceListing)
            .filter(
                MarketplaceListing.company_id == connection.company_id,
                MarketplaceListing.remote_listing_id == str(data.get("listing_id") or ""),
            )
            .first()
        )
        if listing is None:
            return "ignored", "listing not found locally"
        listing.status = data.get("status") or "paused"
        listing.last_error = data.get("reason")
        return "applied", None

    if not event_type.startswith("order."):
        # Unknown event families are recorded and the cursor still advances —
        # additive server changes must never wedge an older client (contract §7).
        return "ignored", f"unknown event type {event_type}"

    remote_order_id = str(event.get("order_id") or data.get("order_id") or "")
    order = (
        db.query(MarketplaceOrder)
        .filter(
            MarketplaceOrder.company_id == connection.company_id,
            MarketplaceOrder.remote_order_id == remote_order_id,
        )
        .first()
    )

    if event_type == "order.created":
        if order is not None:
            return "ignored", "order already known"
        order = upsert_order_from_snapshot(
            db, connection, data, _EVENT_SIDE["order.created"]
        )
        order.state = "pending"
        order.last_event_seq = seq
        return "applied", None

    if order is None:
        return "ignored", f"no local order {remote_order_id}"

    # seq is monotonic per subscriber; anything not ahead of what we already
    # applied is a redelivery of something older.
    if seq and seq <= (order.last_event_seq or 0):
        return "ignored", "stale event seq"

    allowed = _ALLOWED_FROM.get(event_type)
    if allowed is not None and order.state not in allowed:
        return "ignored", f"{event_type} unreachable from state {order.state}"

    if event_type == "order.cancelled":
        order.state = "cancelled"
        order.closed_at = _parse_dt(data.get("closed_at")) or datetime.utcnow()
    elif event_type == "order.expired":
        order.state = "expired"
        order.closed_at = _parse_dt(data.get("closed_at")) or datetime.utcnow()
    elif event_type == "order.accepted":
        order.state = "accepted"
        order.accepted_at = _parse_dt(data.get("accepted_at")) or datetime.utcnow()
        # Deliberately NOT posting_state='pending'. The buyer must wait for
        # order.posted — posting off accepted alone leaves an orphan document if
        # the seller's own posting then fails.
    elif event_type == "order.rejected":
        order.state = "rejected"
        order.reject_reason = data.get("reason") or data.get("reject_reason")
        order.reject_note = data.get("note") or data.get("reject_note")
        order.closed_at = _parse_dt(data.get("closed_at")) or datetime.utcnow()
    elif event_type == "order.posted":
        order.state = "posted"
        order.seller_invoice_number = data.get("invoice_number")
        order.seller_invoice_date = _parse_dt(data.get("invoice_date"))
        try:
            posting_service.validate_posted_payload(order, data)
        except posting_service.PostingError as exc:
            # A compromised central server can fabricate this payload for a real
            # order. Refuse loudly rather than booking it.
            order.posting_state = "failed"
            order.posting_error = f"{exc.code}: {exc.detail}"[:1000]
            order.last_event_seq = seq
            return "error", exc.detail
        order.posting_warnings = _tax_divergence_warning(order, data)
        order.posting_state = "pending"
    elif event_type == "order.buyer_posted":
        # Informational to the seller only. The full payload is kept in the event
        # ledger; there is nothing on the order to advance.
        pass
    else:
        order.last_event_seq = seq
        return "ignored", f"unknown order event {event_type}"

    order.last_event_seq = seq
    return "applied", None


def _tax_divergence_warning(order: MarketplaceOrder, payload: dict) -> str | None:
    """Flag a seller rate/HSN that differs from the order we hold.

    Not part of the mandatory match list, so it does not refuse the post — but
    it is exactly the case that produces two legally-linked invoices with
    different tax, so it must be visible rather than silent.
    """
    held = {item.line_no: item for item in order.items}
    warnings = []
    for line in payload.get("lines") or []:
        item = held.get(int(line.get("line_no") or 0))
        if item is None:
            continue
        if line.get("gst_rate") is not None and _dec(line["gst_rate"]) != _dec(item.gst_rate):
            warnings.append(
                f"line {item.line_no}: seller gst_rate {line['gst_rate']} != {item.gst_rate}"
            )
        if line.get("hsn_sac") and line["hsn_sac"] != item.hsn_sac:
            warnings.append(
                f"line {item.line_no}: seller hsn_sac {line['hsn_sac']} != {item.hsn_sac}"
            )
    return "; ".join(warnings)[:1000] or None


def _process_event(
    db: Session, connection: MarketplaceConnection, event: dict
) -> str:
    """Apply one event in its own transaction: ledger insert first, then the
    state change, then the cursor, then COMMIT. Returns applied|ignored|duplicate."""
    event_id = str(event.get("event_id") or "")
    seq = int(event.get("seq") or 0)

    ledger_row = MarketplaceProcessedEvent(
        company_id=connection.company_id,
        event_id=event_id,
        event_type=str(event.get("type") or ""),
        seq=seq,
        remote_order_id=str(event.get("order_id") or "") or None,
        result="applied",
        payload=json.dumps(event)[:20000],
    )
    db.add(ledger_row)
    try:
        # First statement of the transaction on purpose: a redelivered event must
        # fail here, before anything has been applied.
        db.flush()
    except IntegrityError:
        db.rollback()
        return "duplicate"

    try:
        result, error = apply_event(db, connection, event)
    except Exception as exc:  # noqa: BLE001 — one bad event must not stall the feed
        db.rollback()
        logger.warning("marketplace: event %s failed to apply: %s", event_id, exc)
        db.add(
            MarketplaceProcessedEvent(
                company_id=connection.company_id,
                event_id=event_id,
                event_type=str(event.get("type") or ""),
                seq=seq,
                remote_order_id=str(event.get("order_id") or "") or None,
                result="error",
                error=str(exc)[:1000],
                payload=json.dumps(event)[:20000],
            )
        )
        connection.sync_cursor = max(int(connection.sync_cursor or 0), seq)
        db.commit()
        return "ignored"

    ledger_row.result = result
    ledger_row.error = error
    connection.sync_cursor = max(int(connection.sync_cursor or 0), seq)
    db.commit()
    return "applied" if result == "applied" else "ignored"


# ---------------------------------------------------------------------------
# Full reconcile (cursor_too_old)
# ---------------------------------------------------------------------------

def full_reconcile(db: Session, connection: MarketplaceConnection, client) -> None:
    """Rebuild order state from ``GET /orders`` after the cursor fell out of
    retention. The event ledger is untouched, so already-posted orders stay
    posted and the reconciler will not re-post them."""
    for role, side in (("seller", "sell"), ("buyer", "buy")):
        try:
            body = client.list_orders(role=role, page_size=100)
        except MarketplaceError as exc:
            logger.warning("marketplace: reconcile %s failed: %s", role, exc)
            continue
        for snapshot in body.get("items") or body.get("orders") or []:
            order = upsert_order_from_snapshot(db, connection, snapshot, side)
            if (
                side == "buy"
                and order.state == "posted"
                and order.posting_state == "not_required"
            ):
                # The order.posted event — and with it the payload the divergence
                # check needs — is gone. Surface the order for a human rather than
                # auto-posting a purchase invoice off a snapshot nothing validated.
                order.seller_invoice_number = (
                    snapshot.get("seller_invoice_number") or order.seller_invoice_number
                )
                order.posting_state = "failed"
                order.posting_error = (
                    "resynced_needs_review: recovered after cursor_too_old; "
                    "the seller's posting payload could not be validated"
                )
    db.commit()


# ---------------------------------------------------------------------------
# Auto-accept
# ---------------------------------------------------------------------------

def _reject_remotely(client, order: MarketplaceOrder, reason: str, note: str | None = None) -> bool:
    try:
        client.reject_order(order.remote_order_id, reason, note)
        return True
    except MarketplaceConflict:
        # Already moved on centrally (expired/cancelled); the next drain reconciles.
        return False
    except MarketplaceError as exc:
        logger.warning("marketplace: reject %s failed: %s", order.remote_order_id, exc)
        return False


def run_auto_accept(db: Session, connection: MarketplaceConnection, client) -> int:
    """Accept or reject pending sell-side orders against real local stock.

    The marketplace's soft hold is advisory only; this is the authoritative
    reservation, and it must happen before accepting so an unfulfillable order is
    rejected rather than accepted and then failed at posting time.
    """
    if not connection.auto_accept:
        return 0

    orders = (
        db.query(MarketplaceOrder)
        .filter(
            MarketplaceOrder.company_id == connection.company_id,
            MarketplaceOrder.side == "sell",
            MarketplaceOrder.state == "pending",
        )
        .order_by(MarketplaceOrder.id.asc())
        .all()
    )

    handled = 0
    cap = connection.auto_accept_max_amount
    for order in orders:
        if cap is not None and order.remote_total_amount is not None:
            if _dec(order.remote_total_amount) > _dec(cap):
                # Over the cap: same code path, but a human has to click it.
                continue
        handled += accept_or_reject_order(db, connection, order, client) is not None
    return handled


def accept_or_reject_order(
    db: Session, connection: MarketplaceConnection, order: MarketplaceOrder, client
) -> str | None:
    """Stock-check then accept, or reject with ``insufficient_stock``.

    Returns 'accepted' | 'rejected' | None (nothing happened).
    """
    if not posting_service.seller_has_stock(db, connection, order):
        if _reject_remotely(client, order, "insufficient_stock"):
            order.state = "rejected"
            order.reject_reason = "insufficient_stock"
            order.closed_at = datetime.utcnow()
            # No invoice on either side — the buyer's UI says "seller could not fulfil".
            order.posting_state = "not_required"
            db.commit()
            return "rejected"
        return None

    try:
        client.accept_order(order.remote_order_id)
    except MarketplaceConflict as exc:
        logger.info("marketplace: accept %s conflicted: %s", order.remote_order_id, exc)
        return None
    except MarketplaceError as exc:
        logger.warning("marketplace: accept %s failed: %s", order.remote_order_id, exc)
        return None

    order.state = "accepted"
    order.accepted_at = datetime.utcnow()
    # The seller posts immediately; the buyer waits for order.posted.
    order.posting_state = "pending"
    db.commit()
    return "accepted"


# ---------------------------------------------------------------------------
# Posting hand-back
# ---------------------------------------------------------------------------

def report_pending_postings(db: Session, connection: MarketplaceConnection, client) -> int:
    """Tell the central server about invoices we have already committed.

    A failed report leaves the order ``posted`` with ``remote_posting_reported``
    false, so only the report is retried — never the post.
    """
    from src.models.invoice import Invoice  # local import: avoids a cycle at module load

    orders = (
        db.query(MarketplaceOrder)
        .filter(
            MarketplaceOrder.company_id == connection.company_id,
            MarketplaceOrder.posting_state == "posted",
            MarketplaceOrder.remote_posting_reported.is_(False),
            MarketplaceOrder.posted_invoice_id.isnot(None),
        )
        .order_by(MarketplaceOrder.id.asc())
        .limit(25)
        .all()
    )

    reported = 0
    for order in orders:
        invoice = db.query(Invoice).filter(Invoice.id == order.posted_invoice_id).first()
        if invoice is None:
            continue
        try:
            if order.side == "sell":
                client.report_posting(
                    order.remote_order_id,
                    posting_service.build_posting_report(order, invoice),
                )
            else:
                client.report_buyer_posting(
                    order.remote_order_id,
                    {
                        "invoice_number": invoice.invoice_number,
                        "invoice_date": invoice.invoice_date.date().isoformat()
                        if isinstance(invoice.invoice_date, datetime)
                        else None,
                    },
                )
        except MarketplaceConflict:
            # The server already has it (idempotency replay) — stop retrying.
            pass
        except MarketplaceError as exc:
            logger.warning(
                "marketplace: posting report for %s failed: %s", order.remote_order_id, exc
            )
            continue
        order.remote_posting_reported = True
        reported += 1
    db.commit()
    return reported


# ---------------------------------------------------------------------------
# Drain
# ---------------------------------------------------------------------------

def drain(
    db: Session,
    connection: MarketplaceConnection,
    *,
    client=None,
    max_pages: int = MAX_PAGES,
    budget_seconds: float = DRAIN_BUDGET_SECONDS,
    run_posting: bool = True,
) -> SyncResultOut:
    """Drain the event feed for one connection, then run the posting pass."""
    result = SyncResultOut(
        company_id=connection.company_id, cursor=int(connection.sync_cursor or 0)
    )

    if connection.status in ("unregistered", "unauthorized") or not connection.credential:
        result.error = "not_connected"
        return result

    if not acquire_sync_lock(db, connection):
        result.locked = True
        return result

    result.ran = True
    owns_client = client is None
    error: str | None = None
    started = time.monotonic()

    try:
        client = client or client_for_connection(connection)
        for _page in range(max_pages):
            if time.monotonic() - started > budget_seconds:
                break
            try:
                body = client.get_events(int(connection.sync_cursor or 0), PAGE_SIZE)
            except MarketplaceConflict as exc:
                if exc.code != "cursor_too_old":
                    raise
                full_reconcile(db, connection, client)
                connection.sync_cursor = int(exc.payload.get("resync_from") or 0)
                db.commit()
                result.resynced = True
                continue

            events = body.get("events") or []
            result.events_fetched += len(events)
            for event in events:
                outcome = _process_event(db, connection, event)
                if outcome == "applied":
                    result.events_applied += 1
                elif outcome == "duplicate":
                    result.events_skipped += 1
                else:
                    result.events_ignored += 1

            next_since = body.get("next_since")
            if next_since is not None:
                connection.sync_cursor = max(
                    int(connection.sync_cursor or 0), int(next_since)
                )
                db.commit()
            if not body.get("has_more"):
                break

    except MarketplaceAuthError as exc:
        db.rollback()
        connection.status = "unauthorized"
        db.commit()
        error = f"{exc.code}: {exc}"
    except MarketplaceError as exc:
        db.rollback()
        error = f"{exc.code}: {exc}"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("marketplace: drain failed")
        error = str(exc)
    finally:
        release_sync_lock(db, connection, error)
        db.refresh(connection)

    result.error = error
    result.cursor = int(connection.sync_cursor or 0)

    if run_posting and connection.status != "unauthorized":
        try:
            if connection.auto_accept:
                run_auto_accept(db, connection, client or client_for_connection(connection))
            if connection.auto_post:
                posted, failed = posting_service.run_posting_reconciler(db, connection)
                result.posted = posted
                result.posting_failed = failed
            report_pending_postings(
                db, connection, client or client_for_connection(connection)
            )
        except MarketplaceError as exc:
            result.error = result.error or f"{exc.code}: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("marketplace: posting pass failed")
            result.error = result.error or str(exc)

    if owns_client and client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    return result


def drain_all(db: Session, **kwargs) -> list[SyncResultOut]:
    """Drain every connected company. Backs the cron-driven ``/sync-all``, the
    only path that works when nobody has the app open."""
    connections = (
        db.query(MarketplaceConnection)
        .filter(MarketplaceConnection.status.in_(["connected", "pending_approval", "suspended"]))
        .order_by(MarketplaceConnection.id.asc())
        .all()
    )
    return [drain(db, connection, **kwargs) for connection in connections]


def maybe_drain(
    db: Session, connection: MarketplaceConnection, *, min_age_seconds: int = 20, **kwargs
) -> SyncResultOut | None:
    """Opportunistic drain from a read endpoint, skipped if we synced recently."""
    if connection.last_sync_at is not None:
        age = (datetime.utcnow() - connection.last_sync_at).total_seconds()
        if age < min_age_seconds:
            return None
    kwargs.setdefault("budget_seconds", 8.0)
    return drain(db, connection, **kwargs)
