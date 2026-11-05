"""The legacy bootstrap year should not warn on the first invoice."""
from datetime import date
from pathlib import Path

import pytest

from migrate import load_migration_module
from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.invoice import Invoice
from src.models.invoice_series import InvoiceSeries

TODAY = date(2026, 4, 1)
MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations"
    / "20261106000001_seed_current_fy_for_fresh_single_tenant.py"
)


@pytest.fixture
def seeded_install(client, db_session, monkeypatch):
    # Get the company selected by the app, then reproduce the original
    # migration's placeholder and company-scoped 2025-26 rows.
    company_id = client.get("/api/company/").json()["id"]
    company = db_session.get(CompanyProfile, company_id)
    company.name, company.address, company.gst = "Default Company", "", ""
    year = FinancialYear(company_id=company_id, label="2025-26", is_active=True,
                         start_date=date(2025, 4, 1), end_date=date(2026, 3, 31))
    db_session.add(year)
    db_session.flush()
    db_session.add(InvoiceSeries(
        company_id=company_id, voucher_type="sales", financial_year_id=year.id, prefix="INV",
    ))
    db_session.commit()
    migration = load_migration_module(MIGRATION)
    monkeypatch.setattr(migration, "india_today", lambda: TODAY)
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    return company_id, year.id, migration


def test_fresh_install_first_invoice_uses_current_year(client, db_session, seeded_install):
    _, old_year_id, migration = seeded_install
    migration.up(db_session.connection())
    migration.up(db_session.connection())  # replay must not duplicate rows
    db_session.commit()

    years = client.get("/api/financial-years/").json()
    active, = [year for year in years if year["is_active"]]
    product = client.post("/api/products/", json={
        "sku": "FY-NEW", "name": "Setup product", "price": 10, "gst_rate": 0,
        "maintain_inventory": False,
    })
    buyer = client.post("/api/ledgers/", json={
        "name": "First buyer", "address": "Test address", "phone_number": "1234567890",
    })
    assert product.status_code == buyer.status_code == 200
    invoice = client.post("/api/invoices/", json={
        "ledger_id": buyer.json()["id"], "invoice_date": TODAY.isoformat(),
        "items": [{"product_id": product.json()["id"], "quantity": 1, "unit_price": 10, "gst_rate": 0}],
    })
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["warnings"] == []
    assert active["label"] == "2026-27"
    assert active["id"] != old_year_id
    assert len(years) == 2
    assert invoice.json()["invoice_number"] == "INV-2026-001"


@pytest.mark.parametrize("existing_invoice,mode", [(True, "single_tenant"), (False, "shared_hosting")])
def test_preserves_active_year_for_used_or_shared_install(
    db_session, seeded_install, monkeypatch, existing_invoice, mode,
):
    company_id, old_year_id, migration = seeded_install
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", mode)
    if existing_invoice:
        db_session.add(Invoice(company_id=company_id, created_by=1, total_amount=10,
                               financial_year_id=old_year_id))
        db_session.flush()
    migration.up(db_session.connection())
    db_session.expire_all()

    year, = db_session.query(FinancialYear).all()
    assert year.id == old_year_id
    assert year.is_active
