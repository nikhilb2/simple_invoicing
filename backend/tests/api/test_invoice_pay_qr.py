"""The pay-online QR printed on invoice PDFs.

The QR encodes the invoice's own *share URL*, not a ``upi://`` intent, and that is
the load-bearing choice this file guards. A printed UPI QR would carry whatever was
outstanding the day it was printed, never expire, and stay payable a month after the
invoice was settled. A printed URL reprices itself on every open.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import segno

from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.company_account import CompanyAccount
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.share_link import ShareLink
from src.models.user import User, UserRole


def _company(db, *, pay_qr: bool) -> CompanyProfile:
    company = CompanyProfile(
        name="Alpha Ltd",
        address="1 Test Road",
        gst="27AAAAA0000A1Z5",
        currency_code="INR",
        show_pay_qr_on_invoice=pay_qr,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _user(db) -> User:
    user = db.query(User).filter(User.email == "owner@example.com").first()
    if user:
        return user
    user = User(
        email="owner@example.com",
        full_name="Owner",
        hashed_password="x",
        role=UserRole.admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _invoice(db, company: CompanyProfile) -> Invoice:
    user = _user(db)
    ledger = Ledger(
        company_id=company.id,
        name="Acme Traders",
        address="9 Buyer Lane",
        gst="27BBBBB0000B1Z5",
        phone_number="+91 9111111111",
    )
    db.add(ledger)
    db.add(CompanyAccount(
        company_id=company.id,
        account_type="bank",
        display_name="Main current account",
        bank_name="HDFC Bank",
        account_name="Alpha Ltd",
        upi_vpa="alpha@okhdfcbank",
        display_on_invoice=True,
        is_active=True,
    ))
    product = Product(
        company_id=company.id, sku="SKU-1", name="Widget",
        price=Decimal("100.00"), gst_rate=Decimal("18.00"),
    )
    db.add(product)
    db.commit()
    db.refresh(ledger)
    db.refresh(product)

    invoice = Invoice(
        invoice_number="INV-0042",
        company_id=company.id,
        ledger_id=ledger.id,
        ledger_name=ledger.name,
        company_name=company.name,
        company_currency_code="INR",
        voucher_type="sales",
        status="active",
        created_by=user.id,
        taxable_amount=Decimal("100.00"),
        total_tax_amount=Decimal("18.00"),
        total_amount=Decimal("118.00"),
        invoice_date=datetime(2026, 6, 1, 10, 0, 0),
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    db.add(InvoiceItem(
        invoice_id=invoice.id, product_id=product.id, quantity=Decimal("1.000"),
        unit_price=Decimal("100.00"), gst_rate=Decimal("18.00"),
        taxable_amount=Decimal("100.00"), tax_amount=Decimal("18.00"),
        line_total=Decimal("118.00"),
    ))
    db.commit()
    db.refresh(invoice)
    return invoice


def _headers(company: CompanyProfile) -> dict[str, str]:
    return {"X-Company-Id": str(company.id)}


def test_no_qr_and_no_link_until_the_company_opts_in(client, db_session):
    # The feature ships dark. Downloading your own invoice must not quietly publish
    # a publicly reachable URL for it.
    company = _company(db_session, pay_qr=False)
    invoice = _invoice(db_session, company)

    response = client.get(f"/api/invoices/{invoice.id}/pdf", headers=_headers(company))
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert db_session.query(ShareLink).filter(ShareLink.company_id == company.id).count() == 0


def test_opting_in_mints_the_link_and_prints_its_qr(client, db_session):
    company = _company(db_session, pay_qr=True)
    invoice = _invoice(db_session, company)

    with patch("src.services.upi.segno.make", wraps=segno.make) as make:
        response = client.get(f"/api/invoices/{invoice.id}/pdf", headers=_headers(company))
    assert response.status_code == 200

    links = db_session.query(ShareLink).filter(ShareLink.company_id == company.id).all()
    assert len(links) == 1
    assert links[0].resource_type == "invoice"
    assert links[0].resource_id == invoice.id
    assert make.call_count == 1

    # The QR encodes the share URL, tagged so a scan is distinguishable from a link
    # someone forwarded in a chat -- and is emphatically not a upi:// intent.
    encoded = make.call_args.args[0]
    assert f"/s/{links[0].token}?src=qr" in encoded
    assert not encoded.startswith("upi://")


def test_reprinting_reuses_the_same_link_rather_than_minting_another(client, db_session):
    # Two live tokens for one document would leave two URLs in circulation and make
    # revoking only half work.
    company = _company(db_session, pay_qr=True)
    invoice = _invoice(db_session, company)

    for _ in range(3):
        client.get(f"/api/invoices/{invoice.id}/pdf", headers=_headers(company))

    assert db_session.query(ShareLink).filter(ShareLink.company_id == company.id).count() == 1


def test_a_triplicate_print_encodes_the_qr_once(client, db_session):
    # _build_multi_copy_invoice_html re-renders the body per copy, so a QR built
    # inside it would be encoded three times for one document.
    company = _company(db_session, pay_qr=True)
    invoice = _invoice(db_session, company)

    with patch("src.services.upi.segno.make", wraps=segno.make) as make:
        response = client.get(
            f"/api/invoices/{invoice.id}/pdf", params={"copies": 3}, headers=_headers(company)
        )
    assert response.status_code == 200
    assert make.call_count == 1


def test_the_html_carries_one_qr_image_per_copy(db_session):
    from src.services.share_documents import build_invoice_html, document_share_url

    company = _company(db_session, pay_qr=True)
    invoice = _invoice(db_session, company)
    share_url = document_share_url(db_session, None, company, "invoice", invoice.id)

    single = build_invoice_html(db_session, company.id, invoice.id, copies=1, share_url=share_url)
    assert single.count("data:image/png;base64,") == 1
    assert "Pay online" in single

    triple = build_invoice_html(db_session, company.id, invoice.id, copies=3, share_url=share_url)
    assert triple.count("data:image/png;base64,") == 3


def test_a_cancelled_invoice_is_never_published(client, db_session):
    company = _company(db_session, pay_qr=True)
    invoice = _invoice(db_session, company)
    invoice.status = "cancelled"
    db_session.commit()

    client.get(f"/api/invoices/{invoice.id}/pdf", headers=_headers(company))
    assert db_session.query(ShareLink).filter(ShareLink.company_id == company.id).count() == 0
