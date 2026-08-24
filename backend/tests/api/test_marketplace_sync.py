"""End-to-end drain tests against the in-memory fake marketplace.

Both trading parties live in the same SQLite database as two CompanyProfiles
with one connection each, which exercises the seller→buyer round trip and the
company scoping of every query at the same time.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.marketplace import (
    MarketplaceConnection,
    MarketplaceOrder,
    MarketplaceProcessedEvent,
)
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.marketplace import ListingCreateIn
from src.services.marketplace import client as client_module
from src.services.marketplace import listings as listings_service
from src.services.marketplace import sync as sync_service
from src.services.marketplace.client import build_client
from tests.fakes.fake_marketplace import FakeMarketplace

SELLER_GST = "27AABCU9603R1ZX"
BUYER_GST = "29ABCDE1234F1Z5"


@pytest.fixture
def fake():
    marketplace = FakeMarketplace()
    client_module.set_transport_override(marketplace.transport())
    yield marketplace
    client_module.set_transport_override(None)


class Party:
    """One company on this instance, connected to the marketplace."""

    def __init__(self, company, user, connection):
        self.company = company
        self.user = user
        self.connection = connection

    @property
    def company_id(self):
        return self.company.id


def _make_party(db, fake, *, name, gst, email, auto_post=True) -> Party:
    company = CompanyProfile(
        name=name, address=f"{name} HQ", gst=gst, phone_number="9999999999", currency_code="INR"
    )
    user = User(email=email, full_name=name, hashed_password="x", role=UserRole.admin)
    db.add_all([company, user])
    db.flush()
    db.add(
        FinancialYear(
            company_id=company.id,
            label="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
            is_active=True,
        )
    )
    db.flush()

    with build_client("http://marketplace.test") as api:
        response = api.register_seller(
            {
                "gstin": gst,
                "legal_name": name,
                "address": f"{name} HQ",
                "state_code": gst[:2],
                "contact_email": email,
                "contact_phone": "9999999999",
                "instance_id": f"inst-{name}",
                "client_version": "0.1.0",
            }
        )

    connection = MarketplaceConnection(
        company_id=company.id,
        base_url="http://marketplace.test",
        remote_seller_id=response["seller_id"],
        gstin=gst,
        display_name=name,
        instance_uuid=f"inst-{name}",
        status="pending_approval",
        created_by_user_id=user.id,
        auto_accept=True,
        auto_post=auto_post,
        registered_at=datetime.utcnow(),
    )
    connection.credential = response["api_key"]
    db.add(connection)
    db.commit()
    return Party(company, user, connection)


def _publish(db, party, *, qty=100, price="125.00", gst_rate=18, hsn="8482"):
    product = Product(
        company_id=party.company_id,
        sku="BEAR-01",
        name="Bearing 6204-2RS",
        price=Decimal(price),
        purchase_price=Decimal(price),
        gst_rate=gst_rate,
        hsn_sac=hsn,
        unit="Pieces",
        maintain_inventory=True,
    )
    db.add(product)
    db.flush()
    db.add(Inventory(company_id=party.company_id, product_id=product.id, quantity=qty))
    db.commit()

    payload = ListingCreateIn(product_id=product.id, asking_price=float(price))
    listing = listings_service.build_listing(db, party.connection, product, payload)
    with build_client("http://marketplace.test", party.connection.credential) as api:
        listings_service.publish_listing(db, party.connection, listing, api)
    return product, listing


def _place_order(db, buyer, listing_id, quantity="10"):
    with build_client("http://marketplace.test", buyer.connection.credential) as api:
        response = api.create_order(
            {"listing_id": listing_id, "quantity": quantity}
        )
    order = sync_service.upsert_order_from_snapshot(db, buyer.connection, response, "buy")
    order.posting_state = "not_required"
    db.commit()
    return order


def _stock(db, company_id, product_id) -> Decimal:
    row = (
        db.query(Inventory)
        .filter(Inventory.company_id == company_id, Inventory.product_id == product_id)
        .first()
    )
    return Decimal(str(row.quantity)) if row else Decimal("0")


def _invoices(db, company_id):
    return db.query(Invoice).filter(Invoice.company_id == company_id).all()


@pytest.fixture
def parties(db_session, fake):
    seller = _make_party(
        db_session, fake, name="SellerCo", gst=SELLER_GST, email="seller@example.com"
    )
    buyer = _make_party(
        db_session, fake, name="BuyerCo", gst=BUYER_GST, email="buyer@example.com"
    )
    return seller, buyer


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_full_seller_to_buyer_round_trip_agrees_to_the_paisa(self, db_session, fake, parties):
        seller, buyer = parties
        product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        seller_result = sync_service.drain(db_session, seller.connection)
        buyer_result = sync_service.drain(db_session, buyer.connection)

        assert seller_result.error is None
        assert buyer_result.error is None

        sales = _invoices(db_session, seller.company_id)
        purchases = _invoices(db_session, buyer.company_id)
        assert len(sales) == 1
        assert len(purchases) == 1
        sale, purchase = sales[0], purchases[0]

        assert sale.voucher_type == "sales"
        assert purchase.voucher_type == "purchase"
        assert float(sale.taxable_amount) == float(purchase.taxable_amount) == 1250.00
        assert float(sale.total_tax_amount) == float(purchase.total_tax_amount) == 225.00
        assert float(sale.total_amount) == float(purchase.total_amount) == 1475.00
        # 27 vs 29 — interstate on both sides.
        assert float(sale.igst_amount) == float(purchase.igst_amount) == 225.00
        assert purchase.supplier_invoice_number == sale.invoice_number

        buyer_product = (
            db_session.query(Product)
            .filter(Product.company_id == buyer.company_id)
            .one()
        )
        assert buyer_product.sku.startswith("MKT-")
        assert _stock(db_session, seller.company_id, product.id) == Decimal("90.000")
        assert _stock(db_session, buyer.company_id, buyer_product.id) == Decimal("10.000")

        seller_order = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == seller.company_id)
            .one()
        )
        buyer_order = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == buyer.company_id)
            .one()
        )
        assert seller_order.state == "accepted"
        assert seller_order.posting_state == "posted"
        assert seller_order.remote_posting_reported is True
        assert buyer_order.state == "posted"
        assert buyer_order.posting_state == "posted"

    def test_draining_the_same_batch_twice_creates_exactly_one_invoice(
        self, db_session, fake, parties
    ):
        seller, buyer = parties
        product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        for _ in range(3):
            sync_service.drain(db_session, seller.connection)
            sync_service.drain(db_session, buyer.connection)

        assert len(_invoices(db_session, seller.company_id)) == 1
        assert len(_invoices(db_session, buyer.company_id)) == 1
        assert _stock(db_session, seller.company_id, product.id) == Decimal("90.000")

    def test_approval_event_flips_the_connection_without_re_registering(
        self, db_session, fake, parties
    ):
        seller, _buyer = parties
        assert seller.connection.status == "pending_approval"

        sync_service.drain(db_session, seller.connection)

        db_session.refresh(seller.connection)
        assert seller.connection.status == "connected"


# ---------------------------------------------------------------------------
# Idempotency of the feed
# ---------------------------------------------------------------------------

class TestEventLedger:
    def test_duplicate_event_id_is_skipped(self, db_session, fake, parties):
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        sync_service.drain(db_session, seller.connection)
        # The feed redelivers the newest event with the same event_id.
        fake.redeliver_last_event(seller.connection.remote_seller_id)
        result = sync_service.drain(db_session, seller.connection)

        assert result.events_skipped >= 1
        assert result.events_applied == 0
        assert len(_invoices(db_session, seller.company_id)) == 1

    def test_ledger_rows_record_the_outcome_of_every_event(self, db_session, fake, parties):
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        sync_service.drain(db_session, seller.connection)

        rows = (
            db_session.query(MarketplaceProcessedEvent)
            .filter(MarketplaceProcessedEvent.company_id == seller.company_id)
            .all()
        )
        types = {row.event_type for row in rows}
        assert "seller.status_changed" in types
        assert "order.created" in types
        assert all(row.result in ("applied", "ignored", "error") for row in rows)

    def test_unreachable_transition_is_ignored_not_applied(self, db_session, fake, parties):
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        order = _place_order(db_session, buyer, listing.remote_listing_id, "10")
        sync_service.drain(db_session, seller.connection)
        sync_service.drain(db_session, buyer.connection)

        db_session.refresh(order)
        assert order.state == "posted"

        # A late order.accepted must not drag a posted order back.
        fake.inject_out_of_order_event(
            buyer.connection.remote_seller_id, "order.accepted", order.remote_order_id
        )
        result = sync_service.drain(db_session, buyer.connection)

        assert result.events_ignored == 1
        db_session.refresh(order)
        assert order.state == "posted"
        assert len(_invoices(db_session, buyer.company_id)) == 1

    def test_stale_seq_is_dropped(self, db_session, fake, parties):
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        order = _place_order(db_session, buyer, listing.remote_listing_id, "10")
        sync_service.drain(db_session, seller.connection)
        sync_service.drain(db_session, buyer.connection)
        db_session.refresh(order)
        applied_seq = order.last_event_seq

        event = {
            "event_id": "evt_replayed",
            "seq": applied_seq - 1,
            "type": "order.rejected",
            "order_id": order.remote_order_id,
            "data": {"reason": "cannot_ship"},
        }
        result, error = sync_service.apply_event(db_session, buyer.connection, event)

        assert result == "ignored"
        assert "stale" in error
        assert order.state == "posted"

    def test_unknown_event_type_is_ignored_and_the_cursor_still_advances(
        self, db_session, fake, parties
    ):
        """Additive server changes must never wedge an older client."""
        seller, _buyer = parties
        fake.emit(seller.connection.remote_seller_id, "bid.placed", None, {"bid_id": "bid_1"})

        result = sync_service.drain(db_session, seller.connection)

        assert result.events_ignored >= 1
        db_session.refresh(seller.connection)
        assert seller.connection.sync_cursor == result.cursor > 0


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------

class TestDrainLock:
    def test_a_second_drain_finds_the_lock_held(self, db_session, fake, parties):
        seller, _buyer = parties
        assert sync_service.acquire_sync_lock(db_session, seller.connection) is True

        result = sync_service.drain(db_session, seller.connection)

        assert result.locked is True
        assert result.ran is False
        assert result.events_fetched == 0

    def test_an_expired_lock_is_reclaimed(self, db_session, fake, parties):
        seller, _buyer = parties
        seller.connection.sync_lock_until = datetime.utcnow() - timedelta(seconds=1)
        db_session.commit()

        result = sync_service.drain(db_session, seller.connection)

        assert result.locked is False
        assert result.ran is True

    def test_the_lock_is_released_even_when_the_drain_fails(self, db_session, fake, parties):
        seller, _buyer = parties

        def unreachable(_request):
            raise httpx.ConnectError("connection refused")

        client_module.set_transport_override(httpx.MockTransport(unreachable))

        result = sync_service.drain(db_session, seller.connection)

        assert result.error is not None
        db_session.refresh(seller.connection)
        assert seller.connection.sync_lock_until is None
        assert seller.connection.last_sync_error is not None


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

class TestFailures:
    def test_insufficient_local_stock_auto_rejects_with_no_invoice_either_side(
        self, db_session, fake, parties
    ):
        seller, buyer = parties
        product, listing = _publish(db_session, seller, qty=1)
        # The advertised quantity is advisory; the seller's instance is the only
        # authority, so the central hold has to be widened for the race to happen.
        fake.set_listing_quantity(listing.remote_listing_id, "50")
        order = _place_order(db_session, buyer, listing.remote_listing_id, "10")

        sync_service.drain(db_session, seller.connection)
        sync_service.drain(db_session, buyer.connection)

        seller_order = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == seller.company_id)
            .one()
        )
        assert seller_order.state == "rejected"
        assert seller_order.reject_reason == "insufficient_stock"
        db_session.refresh(order)
        assert order.state == "rejected"
        assert _invoices(db_session, seller.company_id) == []
        assert _invoices(db_session, buyer.company_id) == []
        assert _stock(db_session, seller.company_id, product.id) == Decimal("1.000")

    def test_a_failed_post_is_retried_not_duplicated(self, db_session, fake, parties):
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        # No financial year on the seller ⇒ the post fails permanently.
        db_session.query(FinancialYear).filter(
            FinancialYear.company_id == seller.company_id
        ).delete()
        db_session.commit()

        sync_service.drain(db_session, seller.connection)
        seller_order = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == seller.company_id)
            .one()
        )
        assert seller_order.posting_state == "failed"
        assert "no_financial_year" in seller_order.posting_error
        assert _invoices(db_session, seller.company_id) == []

        # Operator adds the FY and the retry posts exactly once.
        db_session.add(
            FinancialYear(
                company_id=seller.company_id,
                label="2026-27",
                start_date=date(2026, 4, 1),
                end_date=date(2027, 3, 31),
                is_active=True,
            )
        )
        db_session.commit()

        from src.services.marketplace import posting as posting_service

        posting_service.post_order(db_session, seller.connection, seller_order.id, force=True)
        sync_service.drain(db_session, seller.connection)

        assert len(_invoices(db_session, seller.company_id)) == 1

    def test_tampered_posted_payload_is_refused(self, db_session, fake, parties):
        """A compromised central server fabricating an order.posted for a real
        order must not get an invoice out of us."""
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        sync_service.drain(db_session, seller.connection)
        fake.tamper_posted_event(buyer.connection.remote_seller_id, quantity="1000")
        sync_service.drain(db_session, buyer.connection)

        buyer_order = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == buyer.company_id)
            .one()
        )
        assert buyer_order.posting_state == "failed"
        assert "payload_diverged_from_order" in buyer_order.posting_error
        assert _invoices(db_session, buyer.company_id) == []

    def test_a_divergent_seller_rate_is_warned_but_the_held_rate_is_booked(
        self, db_session, fake, parties
    ):
        """gst_rate is not on the mandatory match list, so it does not refuse the
        post — but booking it silently is exactly how two linked invoices end up
        with different tax."""
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        sync_service.drain(db_session, seller.connection)
        fake.tamper_posted_event(buyer.connection.remote_seller_id, gst_rate="28.00")
        sync_service.drain(db_session, buyer.connection)

        buyer_order = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == buyer.company_id)
            .one()
        )
        assert buyer_order.posting_state == "posted"
        assert "gst_rate" in (buyer_order.posting_warnings or "")
        purchase = _invoices(db_session, buyer.company_id)[0]
        assert float(purchase.total_tax_amount) == 225.00

    def test_unauthorized_stops_the_sync_and_marks_the_connection(
        self, db_session, fake, parties
    ):
        seller, _buyer = parties
        seller.connection.credential = "mk_live_revoked"
        db_session.commit()

        result = sync_service.drain(db_session, seller.connection)

        assert result.error is not None
        db_session.refresh(seller.connection)
        assert seller.connection.status == "unauthorized"

        # Subsequent drains do not even try.
        again = sync_service.drain(db_session, seller.connection)
        assert again.error == "not_connected"


# ---------------------------------------------------------------------------
# cursor_too_old
# ---------------------------------------------------------------------------

class TestCursorTooOld:
    def test_a_resynced_posted_order_is_never_auto_posted(self, db_session, fake, parties):
        """The order.posted payload is gone with the events, so there is nothing
        left to validate against — a human has to look at it."""
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")
        sync_service.drain(db_session, seller.connection)

        fake.force_cursor_too_old(buyer.connection.remote_seller_id)
        result = sync_service.drain(db_session, buyer.connection)

        assert result.resynced is True
        buyer_order = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == buyer.company_id)
            .one()
        )
        assert buyer_order.state == "posted"
        assert buyer_order.posting_state == "failed"
        assert "resynced_needs_review" in buyer_order.posting_error
        assert _invoices(db_session, buyer.company_id) == []

    def test_a_later_snapshot_cannot_rewrite_the_lines_we_hold(self, db_session, fake, parties):
        """Those lines are the reference the divergence check compares against."""
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        order = _place_order(db_session, buyer, listing.remote_listing_id, "10")

        tampered = {
            "order_id": order.remote_order_id,
            "state": "accepted",
            "lines": [
                {
                    "line_no": 1,
                    "listing_id": listing.remote_listing_id,
                    "quantity": "1000",
                    "unit_price": "0.01",
                    "gst_rate": "0",
                }
            ],
        }
        sync_service.upsert_order_from_snapshot(db_session, buyer.connection, tampered, "buy")
        db_session.commit()

        db_session.refresh(order)
        assert len(order.items) == 1
        assert Decimal(str(order.items[0].quantity)) == Decimal("10")
        assert Decimal(str(order.items[0].unit_price)) == Decimal("125.00")

    def test_falls_back_to_a_full_reconcile_and_resumes(self, db_session, fake, parties):
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        seller_id = seller.connection.remote_seller_id
        fake.force_cursor_too_old(seller_id)

        result = sync_service.drain(db_session, seller.connection)

        assert result.resynced is True
        assert result.error is None
        order = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == seller.company_id)
            .one()
        )
        # Order state was recovered from GET /orders, not from the lost events.
        assert order.remote_order_id.startswith("ord_")
        db_session.refresh(seller.connection)
        assert seller.connection.sync_cursor >= fake.retention_floor[seller_id]


# ---------------------------------------------------------------------------
# Scoping and sync-all
# ---------------------------------------------------------------------------

class TestScoping:
    def test_one_companys_drain_never_touches_the_others_rows(
        self, db_session, fake, parties
    ):
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        sync_service.drain(db_session, seller.connection)

        seller_orders = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == seller.company_id)
            .all()
        )
        buyer_orders = (
            db_session.query(MarketplaceOrder)
            .filter(MarketplaceOrder.company_id == buyer.company_id)
            .all()
        )
        assert len(seller_orders) == 1 and seller_orders[0].side == "sell"
        assert len(buyer_orders) == 1 and buyer_orders[0].side == "buy"
        assert _invoices(db_session, buyer.company_id) == []
        assert (
            db_session.query(MarketplaceProcessedEvent)
            .filter(MarketplaceProcessedEvent.company_id == buyer.company_id)
            .count()
            == 0
        )

    def test_drain_all_covers_every_connected_company(self, db_session, fake, parties):
        seller, buyer = parties
        _product, listing = _publish(db_session, seller)
        _place_order(db_session, buyer, listing.remote_listing_id, "10")

        first = sync_service.drain_all(db_session)
        second = sync_service.drain_all(db_session)

        assert {r.company_id for r in first} == {seller.company_id, buyer.company_id}
        assert len(_invoices(db_session, seller.company_id)) == 1
        # The second pass drains the seller's posting report into the buyer.
        assert len(_invoices(db_session, buyer.company_id)) == 1
        assert all(r.error is None for r in second)

    def test_maybe_drain_skips_a_recent_sync(self, db_session, fake, parties):
        seller, _buyer = parties
        sync_service.drain(db_session, seller.connection)
        db_session.refresh(seller.connection)

        assert sync_service.maybe_drain(db_session, seller.connection) is None

        seller.connection.last_sync_at = datetime.utcnow() - timedelta(minutes=5)
        db_session.commit()
        assert sync_service.maybe_drain(db_session, seller.connection) is not None
