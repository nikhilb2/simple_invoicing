"""Tests for marketplace invoice posting — the part that touches the books.

Modelled on tests/api/test_invoice_tax_split.py for the CGST/SGST vs IGST
assertions, and on tests/services/test_invoice_processor.py for the seeding.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.marketplace import (
    MarketplaceConnection,
    MarketplaceLedgerLink,
    MarketplaceListing,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplaceProductLink,
)
from src.models.product import Product
from src.models.user import User, UserRole
from src.services.marketplace import posting as posting_service
from src.services.marketplace import sync as sync_service

SELLER_GST = "27AABCU9603R1ZX"
BUYER_SAME_STATE = "27ABCDE1234F1Z5"
BUYER_OTHER_STATE = "29ABCDE1234F1Z5"


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def make_company(db, *, gst=SELLER_GST, name="Test Co") -> CompanyProfile:
    company = CompanyProfile(
        name=name, address="HQ", gst=gst, phone_number="9999999999", currency_code="INR"
    )
    db.add(company)
    db.flush()
    return company


def make_user(db, email="admin@example.com") -> User:
    user = User(
        email=email, full_name="Admin", hashed_password="x", role=UserRole.admin
    )
    db.add(user)
    db.flush()
    return user


def make_fy(db, company_id, *, start=date(2026, 4, 1), end=date(2027, 3, 31)) -> FinancialYear:
    fy = FinancialYear(
        company_id=company_id, label="2026-27", start_date=start, end_date=end, is_active=True
    )
    db.add(fy)
    db.flush()
    return fy


def make_product(db, company_id, *, sku="P1", price=100, gst_rate=18, hsn="8482", qty=100):
    product = Product(
        company_id=company_id,
        sku=sku,
        name=f"Product {sku}",
        price=price,
        purchase_price=price,
        gst_rate=gst_rate,
        hsn_sac=hsn,
        unit="Pieces",
        maintain_inventory=True,
    )
    db.add(product)
    db.flush()
    db.add(Inventory(company_id=company_id, product_id=product.id, quantity=qty))
    db.flush()
    return product


def make_connection(db, company_id, user_id, **kwargs) -> MarketplaceConnection:
    connection = MarketplaceConnection(
        company_id=company_id,
        base_url="http://marketplace.test",
        remote_seller_id=kwargs.pop("remote_seller_id", "sel_self"),
        status="connected",
        created_by_user_id=user_id,
        auto_post=True,
        **kwargs,
    )
    connection.credential = "mk_live_test"
    db.add(connection)
    db.flush()
    return connection


def make_order(
    db,
    company_id,
    *,
    side="sell",
    state="accepted",
    remote_order_id="ord_1",
    counterparty_gstin=BUYER_SAME_STATE,
    listing_id="lst_1",
    quantity="10",
    unit_price="125.00",
    gst_rate="18.00",
    hsn="8482",
    total=None,
    posting_state="pending",
) -> MarketplaceOrder:
    quantity_dec = Decimal(quantity)
    price_dec = Decimal(unit_price)
    order = MarketplaceOrder(
        company_id=company_id,
        side=side,
        remote_order_id=remote_order_id,
        state=state,
        remote_listing_id=listing_id,
        counterparty_remote_id="sel_other",
        counterparty_name="Counterparty Ltd",
        counterparty_gstin=counterparty_gstin,
        counterparty_address="Their Street",
        counterparty_phone="8888888888",
        currency_code="INR",
        remote_total_amount=Decimal(total) if total else None,
        order_placed_at=datetime(2026, 8, 22, 10, 0, 0),
        posting_state=posting_state,
    )
    db.add(order)
    db.flush()
    db.add(
        MarketplaceOrderItem(
            order_id=order.id,
            line_no=1,
            remote_listing_id=listing_id,
            title="Bearing 6204-2RS",
            quantity=quantity_dec,
            unit="Pieces",
            unit_price=price_dec,
            gst_rate=Decimal(gst_rate),
            hsn_sac=hsn,
        )
    )
    db.flush()
    db.refresh(order)
    return order


def make_listing(db, company_id, product_id, remote_listing_id="lst_1") -> MarketplaceListing:
    listing = MarketplaceListing(
        company_id=company_id,
        product_id=product_id,
        remote_listing_id=remote_listing_id,
        title="Bearing 6204-2RS",
        asking_price=Decimal("125.00"),
        gst_rate=Decimal("18.00"),
        hsn_sac="8482",
        status="active",
    )
    db.add(listing)
    db.flush()
    return listing


class StubClient:
    """Records outbound calls without any HTTP."""

    def __init__(self):
        self.accepted = []
        self.rejected = []
        self.reports = []

    def accept_order(self, order_id, **_kwargs):
        self.accepted.append(order_id)
        return {"state": "accepted"}

    def reject_order(self, order_id, reason, note=None):
        self.rejected.append((order_id, reason))
        return {"state": "rejected"}

    def report_posting(self, order_id, payload, **_kwargs):
        self.reports.append((order_id, payload))
        return {"state": "posted"}

    def report_buyer_posting(self, order_id, payload):
        self.reports.append((order_id, payload))
        return {"ok": True}


def inventory_of(db, company_id, product_id) -> Decimal:
    row = (
        db.query(Inventory)
        .filter(Inventory.company_id == company_id, Inventory.product_id == product_id)
        .first()
    )
    return Decimal(str(row.quantity)) if row else Decimal("0")


# ---------------------------------------------------------------------------
# Seller side
# ---------------------------------------------------------------------------

class TestSellerPosting:
    def test_intrastate_sale_books_cgst_sgst_and_decrements_stock(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        make_fy(db_session, company.id)
        product = make_product(db_session, company.id, qty=100)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        order = make_order(db_session, company.id, counterparty_gstin=BUYER_SAME_STATE)
        db_session.commit()

        assert posting_service.post_order(db_session, connection, order.id) == "posted"

        db_session.refresh(order)
        invoice = db_session.query(Invoice).filter(Invoice.id == order.posted_invoice_id).one()
        assert invoice.voucher_type == "sales"
        assert float(invoice.taxable_amount) == pytest.approx(1250.00)
        assert float(invoice.cgst_amount) == pytest.approx(112.50)
        assert float(invoice.sgst_amount) == pytest.approx(112.50)
        assert float(invoice.igst_amount) == pytest.approx(0)
        assert float(invoice.total_amount) == pytest.approx(1475.00)
        assert invoice.reference_notes == "Marketplace order ord_1"
        # Both sides are forced tax-exclusive with no round-off so the two
        # documents agree to the paisa.
        assert invoice.tax_inclusive is False
        assert invoice.apply_round_off is False
        assert inventory_of(db_session, company.id, product.id) == Decimal("90.000")

    def test_interstate_sale_books_igst(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        make_fy(db_session, company.id)
        product = make_product(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        order = make_order(db_session, company.id, counterparty_gstin=BUYER_OTHER_STATE)
        db_session.commit()

        posting_service.post_order(db_session, connection, order.id)

        db_session.refresh(order)
        invoice = db_session.query(Invoice).filter(Invoice.id == order.posted_invoice_id).one()
        assert float(invoice.igst_amount) == pytest.approx(225.00)
        assert float(invoice.cgst_amount) == pytest.approx(0)
        assert float(invoice.sgst_amount) == pytest.approx(0)

    def test_counterparty_ledger_is_created_once_and_reused(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        make_fy(db_session, company.id)
        product = make_product(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        first = make_order(db_session, company.id, remote_order_id="ord_1")
        second = make_order(db_session, company.id, remote_order_id="ord_2")
        db_session.commit()

        posting_service.post_order(db_session, connection, first.id)
        posting_service.post_order(db_session, connection, second.id)

        ledgers = db_session.query(Buyer).filter(Buyer.company_id == company.id).all()
        assert len(ledgers) == 1
        assert ledgers[0].gst == BUYER_SAME_STATE
        # ux_buyers_company_id_gst makes a blind second insert raise, so the
        # find-before-create is not optional.
        assert db_session.query(MarketplaceLedgerLink).count() == 1

    def test_existing_ledger_with_the_same_gstin_is_reused_not_duplicated(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        make_fy(db_session, company.id)
        product = make_product(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        existing = Buyer(
            company_id=company.id,
            name="Already Known Ltd",
            address="Old Street",
            gst=BUYER_SAME_STATE,
            phone_number="7777777777",
        )
        db_session.add(existing)
        db_session.flush()
        order = make_order(db_session, company.id)
        db_session.commit()

        posting_service.post_order(db_session, connection, order.id)

        db_session.refresh(order)
        invoice = db_session.query(Invoice).filter(Invoice.id == order.posted_invoice_id).one()
        assert invoice.ledger_id == existing.id
        assert db_session.query(Buyer).filter(Buyer.company_id == company.id).count() == 1

    def test_posting_report_payload_carries_decimal_strings(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        make_fy(db_session, company.id)
        product = make_product(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        order = make_order(db_session, company.id)
        db_session.commit()
        posting_service.post_order(db_session, connection, order.id)
        db_session.refresh(order)

        invoice = db_session.query(Invoice).filter(Invoice.id == order.posted_invoice_id).one()
        report = posting_service.build_posting_report(order, invoice)
        assert report["invoice_number"] == invoice.invoice_number
        assert report["total_amount"] == "1475.00"
        assert report["seller_gstin"] == SELLER_GST
        assert report["lines"][0]["quantity"] == "10.000"
        assert isinstance(report["lines"][0]["unit_price"], str)


# ---------------------------------------------------------------------------
# Buyer side
# ---------------------------------------------------------------------------

class TestBuyerPosting:
    def _setup(self, db_session, *, gst_rate="18.00"):
        company = make_company(db_session, gst=SELLER_GST, name="Buyer Co")
        user = make_user(db_session)
        make_fy(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        order = make_order(
            db_session,
            company.id,
            side="buy",
            state="posted",
            counterparty_gstin=BUYER_OTHER_STATE,
            gst_rate=gst_rate,
        )
        order.seller_invoice_number = "INV-2026-27-000042"
        db_session.commit()
        return company, connection, order

    def test_purchase_auto_creates_a_linked_mkt_product_and_increments_stock(self, db_session):
        company, connection, order = self._setup(db_session)

        assert posting_service.post_order(db_session, connection, order.id) == "posted"

        product = db_session.query(Product).filter(Product.company_id == company.id).one()
        assert product.sku == "MKT-lst_1"
        assert product.hsn_sac == "8482"
        assert float(product.gst_rate) == pytest.approx(18.00)
        # Permissive on purpose — never reject the seller's quantity.
        assert product.allow_decimal is True
        assert product.company_id == company.id

        link = db_session.query(MarketplaceProductLink).one()
        assert link.product_id == product.id
        assert inventory_of(db_session, company.id, product.id) == Decimal("10.000")

        db_session.refresh(order)
        invoice = db_session.query(Invoice).filter(Invoice.id == order.posted_invoice_id).one()
        assert invoice.voucher_type == "purchase"
        assert invoice.supplier_invoice_number == "INV-2026-27-000042"

    def test_second_purchase_from_the_same_listing_reuses_the_linked_product(self, db_session):
        company, connection, order = self._setup(db_session)
        posting_service.post_order(db_session, connection, order.id)

        second = make_order(
            db_session,
            company.id,
            side="buy",
            state="posted",
            remote_order_id="ord_2",
            counterparty_gstin=BUYER_OTHER_STATE,
        )
        db_session.commit()
        posting_service.post_order(db_session, connection, second.id)

        products = db_session.query(Product).filter(Product.company_id == company.id).all()
        assert len(products) == 1
        assert inventory_of(db_session, company.id, products[0].id) == Decimal("20.000")

    def test_sellers_gst_rate_wins_over_a_divergent_local_product(self, db_session):
        """The buyer must book the SELLER's rate, or the two legally-linked
        invoices disagree on tax."""
        company, connection, order = self._setup(db_session, gst_rate="12.00")
        local = make_product(db_session, company.id, sku="LOCAL", gst_rate=28, hsn="9999", qty=0)
        db_session.add(
            MarketplaceProductLink(
                company_id=company.id, remote_listing_id="lst_1", product_id=local.id
            )
        )
        db_session.commit()

        posting_service.post_order(db_session, connection, order.id)

        db_session.refresh(order)
        invoice = db_session.query(Invoice).filter(Invoice.id == order.posted_invoice_id).one()
        item = invoice.items[0]
        assert float(item.gst_rate) == pytest.approx(12.00)
        assert item.hsn_sac == "8482"
        assert float(invoice.total_amount) == pytest.approx(1400.00)

    def test_total_mismatch_is_flagged_but_the_invoice_stands(self, db_session):
        company = make_company(db_session, name="Buyer Co")
        user = make_user(db_session)
        make_fy(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        order = make_order(
            db_session,
            company.id,
            side="buy",
            state="posted",
            counterparty_gstin=BUYER_OTHER_STATE,
            total="9999.99",
        )
        db_session.commit()

        posting_service.post_order(db_session, connection, order.id)

        db_session.refresh(order)
        assert order.posting_state == "posted"
        assert order.posted_invoice_id is not None
        assert order.total_mismatch is True


# ---------------------------------------------------------------------------
# Idempotency and failure handling
# ---------------------------------------------------------------------------

class TestIdempotencyAndFailures:
    def _seller(self, db_session, **order_kwargs):
        company = make_company(db_session)
        user = make_user(db_session)
        make_fy(db_session, company.id)
        product = make_product(db_session, company.id, qty=order_kwargs.pop("stock", 100))
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        order = make_order(db_session, company.id, **order_kwargs)
        db_session.commit()
        return company, connection, order, product

    def test_posting_twice_creates_exactly_one_invoice(self, db_session):
        _company, connection, order, _product = self._seller(db_session)

        assert posting_service.post_order(db_session, connection, order.id) == "posted"
        # The conditional claim finds posting_state='posted', not 'pending'.
        assert posting_service.post_order(db_session, connection, order.id) == "abandoned"

        assert db_session.query(Invoice).count() == 1

    def test_claim_is_conditional_so_a_second_worker_abandons(self, db_session):
        _company, connection, order, _product = self._seller(db_session)

        assert posting_service.claim_order_for_posting(db_session, order.id) is True
        assert posting_service.claim_order_for_posting(db_session, order.id) is False

    def test_missing_financial_year_is_a_permanent_failure(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        product = make_product(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        order = make_order(db_session, company.id)
        db_session.commit()

        assert posting_service.post_order(db_session, connection, order.id) == "failed"

        db_session.refresh(order)
        assert order.posting_state == "failed"
        assert "no_financial_year" in order.posting_error
        # One attempt, not five — a permanent error must never burn the budget.
        assert order.posting_attempts == 1
        assert db_session.query(Invoice).count() == 0

    def test_a_financial_year_is_never_auto_created(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        product = make_product(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        order = make_order(db_session, company.id)
        db_session.commit()

        posting_service.post_order(db_session, connection, order.id)

        assert db_session.query(FinancialYear).count() == 0

    def test_malformed_counterparty_gstin_is_a_permanent_failure(self, db_session):
        _company, connection, order, _product = self._seller(
            db_session, counterparty_gstin="NOT-A-GSTIN"
        )

        assert posting_service.post_order(db_session, connection, order.id) == "failed"

        db_session.refresh(order)
        assert order.posting_state == "failed"
        assert "invalid_counterparty_gstin" in order.posting_error
        assert db_session.query(Invoice).count() == 0

    def test_missing_counterparty_gstin_is_never_treated_as_intrastate(self, db_session):
        _company, connection, order, _product = self._seller(db_session, counterparty_gstin=None)

        assert posting_service.post_order(db_session, connection, order.id) == "failed"
        db_session.refresh(order)
        assert "invalid_counterparty_gstin" in order.posting_error

    def test_transient_failure_retries_then_gives_up_at_five_attempts(self, db_session):
        """Insufficient stock is transient — someone may restock — so it retries,
        but never forever."""
        _company, connection, order, _product = self._seller(db_session, stock=1)

        outcomes = [
            posting_service.post_order(db_session, connection, order.id) for _ in range(6)
        ]
        assert outcomes[:5] == ["failed"] * 5

        db_session.refresh(order)
        assert order.posting_state == "failed"
        assert order.posting_attempts == 5
        # Attempt six could not even claim the row.
        assert outcomes[5] == "abandoned"
        assert db_session.query(Invoice).count() == 0

    def test_retry_after_a_failure_posts_once_not_twice(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        product = make_product(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        order = make_order(db_session, company.id)
        db_session.commit()

        assert posting_service.post_order(db_session, connection, order.id) == "failed"

        # The operator fixes the root cause and hits Retry.
        make_fy(db_session, company.id)
        db_session.commit()
        assert posting_service.post_order(db_session, connection, order.id, force=True) == "posted"
        assert posting_service.post_order(db_session, connection, order.id, force=True) == "abandoned"

        assert db_session.query(Invoice).count() == 1

    def test_stale_posting_lock_is_reclaimed_only_when_no_invoice_exists(self, db_session):
        _company, connection, order, _product = self._seller(db_session)
        posting_service.claim_order_for_posting(db_session, order.id)
        order.posting_lock_until = datetime(2020, 1, 1)
        db_session.commit()

        assert posting_service.reclaim_stale_posting_locks(db_session, connection.company_id) == 1
        db_session.refresh(order)
        assert order.posting_state == "pending"

    def test_a_stale_lock_with_an_invoice_is_never_reclaimed(self, db_session):
        _company, connection, order, _product = self._seller(db_session)
        posting_service.post_order(db_session, connection, order.id)
        db_session.refresh(order)
        order.posting_state = "posting"
        order.posting_lock_until = datetime(2020, 1, 1)
        db_session.commit()

        assert posting_service.reclaim_stale_posting_locks(db_session, connection.company_id) == 0

    def test_reconciler_posts_pending_orders_oldest_first(self, db_session):
        company = make_company(db_session)
        user = make_user(db_session)
        make_fy(db_session, company.id)
        product = make_product(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        make_order(db_session, company.id, remote_order_id="ord_1")
        make_order(db_session, company.id, remote_order_id="ord_2")
        db_session.commit()

        assert posting_service.run_posting_reconciler(db_session, connection) == (2, 0)
        assert db_session.query(Invoice).count() == 2
        assert posting_service.run_posting_reconciler(db_session, connection) == (0, 0)


# ---------------------------------------------------------------------------
# The mandatory divergence check
# ---------------------------------------------------------------------------

class TestPayloadDivergence:
    def _buy_order(self, db_session):
        company = make_company(db_session, name="Buyer Co")
        user = make_user(db_session)
        make_fy(db_session, company.id)
        connection = make_connection(db_session, company.id, user.id)
        order = make_order(
            db_session,
            company.id,
            side="buy",
            state="accepted",
            counterparty_gstin=BUYER_OTHER_STATE,
            posting_state="not_required",
        )
        db_session.commit()
        return connection, order

    def _payload(self, **overrides):
        line = {
            "line_no": 1,
            "listing_id": "lst_1",
            "quantity": "10",
            "unit_price": "125.00",
            "gst_rate": "18.00",
            "hsn_sac": "8482",
        }
        line.update(overrides.pop("line", {}))
        payload = {
            "seller_gstin": BUYER_OTHER_STATE,
            "invoice_number": "INV-1",
            "lines": [line],
        }
        payload.update(overrides)
        return payload

    def test_matching_payload_is_accepted(self, db_session):
        _connection, order = self._buy_order(db_session)
        posting_service.validate_posted_payload(order, self._payload())

    @pytest.mark.parametrize(
        "override",
        [
            {"line": {"quantity": "20"}},
            {"line": {"unit_price": "1.00"}},
            {"line": {"listing_id": "lst_evil"}},
            {"seller_gstin": "07ABCDE1234F1Z5"},
            {"lines": []},
        ],
    )
    def test_any_divergence_is_refused(self, db_session, override):
        _connection, order = self._buy_order(db_session)
        with pytest.raises(posting_service.PostingError) as exc:
            posting_service.validate_posted_payload(order, self._payload(**override))
        assert exc.value.code == "payload_diverged_from_order"
        assert exc.value.permanent is True

    def test_a_diverged_posted_event_refuses_to_post(self, db_session):
        """End to end through the event applier: a fabricated order.posted must
        leave the order failed and the books untouched."""
        connection, order = self._buy_order(db_session)
        event = {
            "event_id": "evt_1",
            "seq": 5,
            "type": "order.posted",
            "order_id": order.remote_order_id,
            "data": self._payload(line={"quantity": "1000"}),
        }

        result, _error = sync_service.apply_event(db_session, connection, event)
        db_session.commit()

        assert result == "error"
        db_session.refresh(order)
        assert order.posting_state == "failed"
        assert "payload_diverged_from_order" in order.posting_error
        assert db_session.query(Invoice).count() == 0


# ---------------------------------------------------------------------------
# Stock check before accepting
# ---------------------------------------------------------------------------

class TestAcceptTimeStockCheck:
    def _seller(self, db_session, *, stock):
        company = make_company(db_session)
        user = make_user(db_session)
        make_fy(db_session, company.id)
        product = make_product(db_session, company.id, qty=stock)
        connection = make_connection(db_session, company.id, user.id)
        make_listing(db_session, company.id, product.id)
        order = make_order(db_session, company.id, state="pending", posting_state="not_required")
        db_session.commit()
        return connection, order, product

    def test_sufficient_stock_accepts_and_queues_the_post(self, db_session):
        connection, order, _product = self._seller(db_session, stock=100)
        client = StubClient()

        assert sync_service.accept_or_reject_order(db_session, connection, order, client) == "accepted"

        db_session.refresh(order)
        assert order.state == "accepted"
        assert order.posting_state == "pending"
        assert client.accepted == ["ord_1"]

    def test_insufficient_stock_auto_rejects_with_no_invoice_either_side(self, db_session):
        connection, order, _product = self._seller(db_session, stock=1)
        client = StubClient()

        assert sync_service.accept_or_reject_order(db_session, connection, order, client) == "rejected"

        db_session.refresh(order)
        assert order.state == "rejected"
        assert order.reject_reason == "insufficient_stock"
        assert order.posting_state == "not_required"
        assert client.accepted == []
        assert client.rejected == [("ord_1", "insufficient_stock")]
        assert db_session.query(Invoice).count() == 0

    def test_auto_accept_respects_the_amount_cap(self, db_session):
        connection, order, _product = self._seller(db_session, stock=100)
        connection.auto_accept_max_amount = Decimal("100.00")
        order.remote_total_amount = Decimal("1475.00")
        db_session.commit()
        client = StubClient()

        sync_service.run_auto_accept(db_session, connection, client)

        db_session.refresh(order)
        assert order.state == "pending"
        assert client.accepted == []

    def test_auto_accept_off_leaves_orders_for_a_human(self, db_session):
        connection, order, _product = self._seller(db_session, stock=100)
        connection.auto_accept = False
        db_session.commit()
        client = StubClient()

        assert sync_service.run_auto_accept(db_session, connection, client) == 0
        db_session.refresh(order)
        assert order.state == "pending"
