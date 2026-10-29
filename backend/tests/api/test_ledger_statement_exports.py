import csv
from datetime import datetime
from io import StringIO

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.user import User, UserRole

PERIOD = {"from_date": "2026-04-01", "to_date": "2026-04-30"}


def _company(company_id: int, name: str) -> CompanyProfile:
    return CompanyProfile(
        id=company_id,
        name=name,
        address="1 Billing Street",
        gst="",
        phone_number="9999999999",
        currency_code="INR",
        email="accounts@example.com",
        website="",
        bank_name="",
        branch_name="",
        account_name="",
        account_number="",
        ifsc_code="",
    )


def _ledger(ledger_id: int, company_id: int, name: str) -> Buyer:
    return Buyer(
        id=ledger_id,
        company_id=company_id,
        name=name,
        address="42 Market Road",
        phone_number="9999999999",
        email="ledger@example.com",
    )


def _invoice(ledger: Buyer, number: str, voucher_type: str, amount: float, when: datetime) -> Invoice:
    return Invoice(
        invoice_number=number,
        company_id=ledger.company_id,
        ledger_id=ledger.id,
        ledger_name=ledger.name,
        ledger_address=ledger.address,
        ledger_phone=ledger.phone_number,
        company_name="Respawn Pvt Ltd",
        company_address="1 Billing Street",
        company_currency_code="INR",
        voucher_type=voucher_type,
        status="active",
        created_by=1,
        taxable_amount=amount,
        total_tax_amount=0,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=0,
        total_amount=amount,
        invoice_date=when,
    )


def _seed_statement(db_session, ledger_name: str = "Acme Stores") -> Buyer:
    """Opening 500 Dr, then a sale, a receipt and a purchase inside April."""
    user = User(id=1, email="test@example.com", full_name="Test Admin", hashed_password="test-hash", role=UserRole.admin)
    company = _company(1, "Respawn Pvt Ltd")
    ledger = _ledger(1, company.id, ledger_name)
    db_session.add_all([user, company, ledger])
    db_session.add_all([
        _invoice(ledger, "S-000", "sales", 500, datetime(2026, 3, 20, 9, 0, 0)),
        _invoice(ledger, "S-001", "sales", 1000.10, datetime(2026, 4, 3, 10, 0, 0)),
        Payment(
            company_id=company.id,
            ledger_id=ledger.id,
            voucher_type="receipt",
            amount=400.20,
            date=datetime(2026, 4, 4, 11, 0, 0),
            payment_number="RCPT-001",
            mode="bank",
            created_by=user.id,
            status="active",
        ),
        _invoice(ledger, "P-001", "purchase", 2000.30, datetime(2026, 4, 5, 12, 0, 0)),
        # After the period: must not reach the CSV.
        _invoice(ledger, "S-002", "sales", 99, datetime(2026, 5, 2, 9, 0, 0)),
    ])
    db_session.commit()
    return ledger


def _rows(response) -> list[list[str]]:
    return list(csv.reader(StringIO(response.text.lstrip("﻿"))))


def test_statement_csv_has_opening_running_balance_and_totals(client, db_session):
    _seed_statement(db_session)

    response = client.get("/api/ledgers/1/statement/csv", params=PERIOD)

    assert response.status_code == 200, response.text
    assert "text/csv" in response.headers["content-type"]
    assert response.headers["content-disposition"] == (
        'attachment; filename="statement_Acme_Stores_2026-04-01_2026-04-30.csv"'
    )
    assert response.content.startswith("﻿".encode("utf-8"))
    assert _rows(response) == [
        ["Date", "Voucher Type", "Reference", "Particulars", "Debit", "Credit", "Balance", "Dr/Cr"],
        ["2026-04-01", "", "", "Opening Balance", "", "", "500.00", "Dr"],
        ["2026-04-03", "Sales", "S-001", "Acme Stores", "1000.10", "", "1500.10", "Dr"],
        ["2026-04-04", "Receipt", "RCPT-001", "Receipt (bank)", "", "400.20", "1099.90", "Dr"],
        ["2026-04-05", "Purchase", "P-001", "Acme Stores", "", "2000.30", "900.40", "Cr"],
        [],
        ["", "", "", "Totals", "1000.10", "2400.50", "900.40", "Cr"],
    ]


def test_statement_csv_totals_match_the_json_statement(client, db_session):
    _seed_statement(db_session)

    statement = client.get("/api/ledgers/1/statement", params=PERIOD).json()
    rows = _rows(client.get("/api/ledgers/1/statement/csv", params=PERIOD))

    def signed(row: list[str]) -> float:
        return float(row[6]) * (-1 if row[7] == "Cr" else 1)

    opening, entries, totals = rows[1], rows[2:-2], rows[-1]
    assert signed(opening) == round(statement["opening_balance"], 2)
    assert [row[2] for row in entries] == [entry["reference_number"] for entry in statement["entries"]]
    assert float(totals[4]) == round(statement["period_debit"], 2)
    assert float(totals[5]) == round(statement["period_credit"], 2)
    assert signed(totals) == round(statement["closing_balance"], 2)
    # The last running balance is the closing balance.
    assert entries[-1][6:] == totals[6:]


def test_statement_csv_for_an_empty_period_still_has_opening_and_totals(client, db_session):
    _seed_statement(db_session)

    rows = _rows(client.get("/api/ledgers/1/statement/csv", params={"from_date": "2026-06-01", "to_date": "2026-06-30"}))

    assert rows[1] == ["2026-06-01", "", "", "Opening Balance", "", "", "801.40", "Cr"]
    assert rows[2] == []
    assert rows[3] == ["", "", "", "Totals", "0.00", "0.00", "801.40", "Cr"]


def test_statement_csv_shows_a_settled_balance_as_zero_without_a_side(client, db_session):
    user = User(id=1, email="test@example.com", full_name="Test Admin", hashed_password="test-hash", role=UserRole.admin)
    company = _company(1, "Respawn Pvt Ltd")
    ledger = _ledger(1, company.id, "Acme Stores")
    db_session.add_all([user, company, ledger])
    db_session.add_all([
        _invoice(ledger, "S-001", "sales", 0.10, datetime(2026, 4, 3, 10, 0, 0)),
        _invoice(ledger, "S-002", "sales", 0.20, datetime(2026, 4, 4, 10, 0, 0)),
        _invoice(ledger, "P-001", "purchase", 0.30, datetime(2026, 4, 5, 10, 0, 0)),
    ])
    db_session.commit()

    rows = _rows(client.get("/api/ledgers/1/statement/csv", params=PERIOD))

    # 0.10 + 0.20 - 0.30 is not 0 in floats.
    assert rows[-3][6:] == ["0.00", ""]
    assert rows[-1] == ["", "", "", "Totals", "0.30", "0.30", "0.00", ""]


def test_statement_csv_keeps_a_non_ascii_ledger_name_out_of_the_header(client, db_session):
    _seed_statement(db_session, ledger_name='श्री "Gupta" Traders')

    response = client.get("/api/ledgers/1/statement/csv", params=PERIOD)

    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        'attachment; filename="statement_Gupta_Traders_2026-04-01_2026-04-30.csv"'
    )
    assert _rows(response)[2][3] == 'श्री "Gupta" Traders'


def test_statement_csv_rejects_an_inverted_range(client, db_session):
    _seed_statement(db_session)

    response = client.get("/api/ledgers/1/statement/csv", params={"from_date": "2026-05-01", "to_date": "2026-04-01"})

    assert response.status_code == 400
    assert response.json()["detail"] == "from_date must be before or equal to to_date"


def test_statement_csv_is_404_for_an_unknown_or_other_company_ledger(client, db_session):
    _seed_statement(db_session)
    db_session.add(_company(2, "Other Co"))
    db_session.add(_ledger(2, 2, "Other Co Customer"))
    db_session.commit()

    unknown = client.get("/api/ledgers/999/statement/csv", params=PERIOD)
    other_company = client.get("/api/ledgers/2/statement/csv", params=PERIOD)

    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Ledger 999 not found"
    assert other_company.status_code == 404
    assert other_company.json()["detail"] == "Ledger 2 not found"
