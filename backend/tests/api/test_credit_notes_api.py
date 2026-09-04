"""The credit note registry, once it holds both directions.

A supplier's note is found by their number, not the one we assigned it — that
is what the user has in front of them when reconciling against GSTR-2B.
"""
from datetime import date, datetime

import pytest

from src.models.buyer import Buyer
from src.models.credit_note import CreditNote
from src.models.user import User, UserRole


@pytest.fixture
def seeded(db_session):
    user = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="secret",
        role=UserRole.admin,
    )
    ledger = Buyer(
        name="Northwind Traders",
        address="1 Dock Road",
        gst="29ABCDE1234F1Z5",
        phone_number="9999999999",
    )
    db_session.add_all([user, ledger])
    db_session.commit()

    outward = CreditNote(
        credit_note_number="CN-2026-001",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction="outward",
        status="active",
        taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0,
        total_amount=118,
        created_at=datetime(2026, 6, 1),
    )
    inward = CreditNote(
        credit_note_number="DN-2026-001",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction="inward",
        supplier_credit_note_number="SUP/CN/12",
        supplier_credit_note_date=date(2026, 6, 2),
        status="active",
        taxable_amount=50, cgst_amount=4.5, sgst_amount=4.5, igst_amount=0,
        total_amount=59,
        created_at=datetime(2026, 6, 2),
    )
    # A row from before the column existed.
    legacy = CreditNote(
        credit_note_number="CN-2025-099",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction=None,
        status="active",
        taxable_amount=10, cgst_amount=0, sgst_amount=0, igst_amount=0,
        total_amount=10,
        created_at=datetime(2026, 6, 3),
    )
    db_session.add_all([outward, inward, legacy])
    db_session.commit()
    return user, ledger


def _list(client, **params):
    response = client.get("/api/credit-notes/", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _numbers(payload):
    return sorted(item["credit_note_number"] for item in payload["items"])


def test_direction_filter_separates_the_two_registries(client, seeded):
    inward = _list(client, direction="inward")
    assert _numbers(inward) == ["DN-2026-001"]

    outward = _list(client, direction="outward")
    # The legacy NULL row counts as outward — nothing before the column was inward.
    assert _numbers(outward) == ["CN-2025-099", "CN-2026-001"]


def test_unfiltered_listing_returns_both(client, seeded):
    result = _list(client)
    assert _numbers(result) == ["CN-2025-099", "CN-2026-001", "DN-2026-001"]


def test_search_matches_the_suppliers_own_number(client, seeded):
    result = _list(client, search="SUP/CN")
    assert _numbers(result) == ["DN-2026-001"]
    assert result["items"][0]["supplier_credit_note_number"] == "SUP/CN/12"
    assert result["items"][0]["supplier_credit_note_date"] == "2026-06-02"


def test_search_still_matches_our_own_number(client, seeded):
    result = _list(client, search="CN-2026")
    assert _numbers(result) == ["CN-2026-001"]


def test_a_legacy_row_reads_back_as_outward(client, seeded):
    """CreditNoteOut must not blow up on a NULL direction."""
    result = _list(client, search="CN-2025-099")
    assert result["items"][0]["direction"] == "outward"


def test_voucher_type_cannot_be_flipped_under_a_credit_note(client, db_session, seeded):
    """Direction is settled at creation; flipping the invoice would strand it.

    It drives numbering, the stock effect and whether the note is filed in
    GSTR-1 — all three would silently go wrong.
    """
    from src.models.credit_note import CreditNoteItem
    from src.models.invoice import Invoice, InvoiceItem
    from src.services.invoice_processor import InvoiceProcessor
    from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
    from src.models.product import Product
    from fastapi import HTTPException

    user, ledger = seeded
    product = Product(sku="P-FLIP", name="Widget", price=100, gst_rate=18)
    db_session.add(product)
    db_session.flush()

    invoice = Invoice(
        invoice_number="INV-FLIP-001",
        ledger_id=ledger.id,
        voucher_type="sales",
        status="active",
        created_by=user.id,
        taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0,
        total_amount=118,
        created_at=datetime(2026, 6, 1),
    )
    db_session.add(invoice)
    db_session.flush()
    item = InvoiceItem(
        invoice_id=invoice.id, product_id=product.id, quantity=1, unit_price=100,
        gst_rate=18, taxable_amount=100, tax_amount=18, line_total=118,
    )
    db_session.add(item)
    db_session.flush()

    note = db_session.query(CreditNote).filter(CreditNote.credit_note_number == "CN-2026-001").one()
    db_session.add(CreditNoteItem(
        credit_note_id=note.id, invoice_id=invoice.id, invoice_item_id=item.id,
        product_id=product.id, quantity=1, unit_price=100, gst_rate=18,
        taxable_amount=100, tax_amount=18, line_total=118,
    ))
    db_session.commit()

    payload = InvoiceCreate(
        ledger_id=ledger.id,
        voucher_type="purchase",
        items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100)],
    )

    with pytest.raises(HTTPException) as exc_info:
        InvoiceProcessor(db_session).apply_payload(invoice, payload, regenerate_number=False)
    assert exc_info.value.status_code == 400
    assert "credit notes against it" in exc_info.value.detail
