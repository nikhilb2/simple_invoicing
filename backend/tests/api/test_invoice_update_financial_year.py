"""Updating an invoice's date must not move it into another financial year.

The financial year (and the number series that comes with it) is chosen at
creation and never recalculated on edit, so a cross-year date change is
blocked with a 400. Same-year changes, and dates no financial year covers,
keep working as before.
"""

from datetime import date

from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear


def _seed_company_and_years(db_session):
    company = CompanyProfile(
        id=1,
        name="FY Test Co",
        address="",
        gst="",
        phone_number="",
        currency_code="INR",
        email="",
        website="",
        bank_name="",
        branch_name="",
        account_name="",
        account_number="",
        ifsc_code="",
    )
    db_session.add(company)
    fy_old = FinancialYear(
        id=1,
        company_id=1,
        label="FY 2025-26",
        start_date=date(2025, 4, 1),
        end_date=date(2026, 3, 31),
        is_active=True,
    )
    fy_new = FinancialYear(
        id=2,
        company_id=1,
        label="FY 2026-27",
        start_date=date(2026, 4, 1),
        end_date=date(2027, 3, 31),
        is_active=False,
    )
    db_session.add_all([fy_old, fy_new])
    db_session.commit()
    return fy_old, fy_new


def _create_ledger(client):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": "FY Customer",
            "address": "Mumbai",
            "gst": "27ABCDE1234F1Z0",
            "phone_number": "9999999999",
            "email": "fycustomer@example.com",
            "website": "",
            "bank_name": "",
            "branch_name": "",
            "account_name": "",
            "account_number": "",
            "ifsc_code": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_product(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "FY-001",
            "name": "FY Product",
            "description": "",
            "hsn_sac": "9988",
            "price": 100,
            "gst_rate": 18,
            "unit": "Pieces",
            "allow_decimal": False,
            "maintain_inventory": False,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _payload(ledger_id, product_id, invoice_date):
    return {
        "ledger_id": ledger_id,
        "voucher_type": "sales",
        "invoice_date": invoice_date,
        "tax_inclusive": False,
        "apply_round_off": False,
        "items": [{"product_id": product_id, "quantity": 1, "unit_price": 100}],
    }


def _create_invoice_in_old_fy(client, ledger_id, product_id):
    response = client.post("/api/invoices/", json=_payload(ledger_id, product_id, "2026-03-28"))
    assert response.status_code == 200, response.text
    return response.json()


def test_update_invoice_date_within_same_fy_works(client, db_session):
    _seed_company_and_years(db_session)
    ledger_id = _create_ledger(client)
    product_id = _create_product(client)
    invoice = _create_invoice_in_old_fy(client, ledger_id, product_id)
    assert invoice["financial_year_id"] == 1

    response = client.put(
        f"/api/invoices/{invoice['id']}",
        json=_payload(ledger_id, product_id, "2026-03-30"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["financial_year_id"] == 1


def test_update_invoice_date_into_other_fy_is_blocked(client, db_session):
    _seed_company_and_years(db_session)
    ledger_id = _create_ledger(client)
    product_id = _create_product(client)
    invoice = _create_invoice_in_old_fy(client, ledger_id, product_id)

    response = client.put(
        f"/api/invoices/{invoice['id']}",
        json=_payload(ledger_id, product_id, "2026-04-02"),
    )

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "FY 2026-27" in detail
    assert "FY 2025-26" in detail

    # The invoice itself is unchanged.
    after = client.get(f"/api/invoices/{invoice['id']}")
    assert after.status_code == 200, after.text
    assert after.json()["financial_year_id"] == 1
    assert after.json()["invoice_date"].startswith("2026-03-28")


def test_update_invoice_date_without_covering_fy_still_works(client, db_session):
    _seed_company_and_years(db_session)
    ledger_id = _create_ledger(client)
    product_id = _create_product(client)
    invoice = _create_invoice_in_old_fy(client, ledger_id, product_id)

    # No financial year covers 2028-05-01: previous behaviour is kept.
    response = client.put(
        f"/api/invoices/{invoice['id']}",
        json=_payload(ledger_id, product_id, "2028-05-01"),
    )

    assert response.status_code == 200, response.text
