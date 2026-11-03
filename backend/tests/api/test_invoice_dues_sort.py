from datetime import datetime

import pytest

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.models.user import User, UserRole


@pytest.fixture
def dues(db_session):
    company = CompanyProfile(id=1, name="Sort Test Co", address="", currency_code="INR")
    user = User(id=1, email="test@example.com", full_name="Tester", hashed_password="x", role=UserRole.admin)
    db_session.add_all([company, user])
    db_session.flush()
    names = ["Zebra", "acme", "Beta", "delta", None]
    amounts = [100, 500, 200, 400, 200]
    due_days = [3, 1, 2, 1, 3]
    invoice_days = [3, 5, 1, 2, 1]
    invoices = []
    for index, name in enumerate(names):
        ledger = Buyer(company_id=1, name=name or "Unnamed", address="", phone_number="")
        db_session.add(ledger)
        db_session.flush()
        invoice = Invoice(
            company_id=1, ledger_id=ledger.id, ledger_name=name, created_by=1,
            invoice_number=f"SORT-{index}", voucher_type="sales", status="active",
            total_amount=amounts[index], invoice_date=datetime(2026, 2, invoice_days[index]),
            due_date=datetime(2026, 3, due_days[index]),
        )
        db_session.add(invoice)
        invoices.append(invoice)
    db_session.flush()
    receipt = Payment(
        company_id=1, ledger_id=invoices[1].ledger_id, voucher_type="receipt",
        amount=400, created_by=1, date=datetime(2026, 2, 10), payment_number="SORT-PAY",
    )
    db_session.add(receipt)
    db_session.flush()
    db_session.add(PaymentInvoiceAllocation(payment_id=receipt.id, invoice_id=invoices[1].id, allocated_amount=400))
    db_session.commit()
    return invoices


def _all_pages(client, sort):
    items = []
    for page in range(1, 4):
        params = {"page": page, "page_size": 2}
        if sort is not None:
            params["sort"] = sort
        response = client.get("/api/invoices/dues", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 5
        assert body["total_pages"] == 3
        items.extend(body["items"])
    return items


@pytest.mark.parametrize("sort,indices", [
    (None, [3, 1, 2, 4, 0]),
    ("default", [3, 1, 2, 4, 0]),
    ("amount-desc", [3, 2, 4, 0, 1]),
    ("due-date-asc", [1, 3, 2, 0, 4]),
    ("customer-asc", [1, 2, 3, 0, 4]),
])
def test_dues_sort_orders_the_complete_result_before_paging(client, dues, sort, indices):
    items = _all_pages(client, sort)
    assert [item["id"] for item in items] == [dues[index].id for index in indices]
    partly_paid = next(item for item in items if item["id"] == dues[1].id)
    assert partly_paid["total_amount"] == 500
    assert partly_paid["outstanding_amount"] == 100


def test_customer_sort_uses_ids_to_break_case_insensitive_name_ties(client, db_session, dues):
    dues[2].ledger_name = " Acme "
    dues[3].ledger_name = "ACME"
    db_session.commit()
    assert [item["id"] for item in _all_pages(client, "customer-asc")] == [
        dues[index].id for index in [1, 2, 3, 0, 4]
    ]


def test_customer_sort_puts_missing_and_blank_names_last_in_id_order(client, db_session, dues):
    dues[0].ledger_name = ""
    dues[2].ledger_name = "   "
    db_session.commit()
    assert [item["id"] for item in _all_pages(client, "customer-asc")] == [
        dues[index].id for index in [1, 3, 0, 2, 4]
    ]


@pytest.mark.parametrize("sort,filters,indices", [
    ("amount-desc", {"search": "a"}, [3, 2, 0, 1]),
    ("customer-asc", {"ledger_id": 1}, [0]),
    ("due-date-asc", {"search": "Beta", "ledger_id": 3}, [2]),
    ("amount-desc", {"due_date_from": "2026-03-02", "due_date_to": "2026-03-03"}, [2, 4, 0]),
])
def test_dues_sort_keeps_other_filters(client, dues, sort, filters, indices):
    response = client.get("/api/invoices/dues", params={"sort": sort, **filters})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [dues[index].id for index in indices]


def test_unknown_dues_sort_is_rejected(client, dues):
    assert client.get("/api/invoices/dues", params={"sort": "unknown"}).status_code == 422


def test_sorting_the_list_keeps_ageing_totals_and_buckets(client, dues):
    before = client.get("/api/invoices/dues/ageing")
    assert before.status_code == 200
    for sort in ("amount-desc", "due-date-asc", "customer-asc"):
        _all_pages(client, sort)
    after = client.get("/api/invoices/dues/ageing")
    assert after.status_code == 200
    assert after.json() == before.json()
    assert after.json()["total_remaining"] == 1000


def test_due_date_sort_handles_missing_dates_last_with_stable_ids():
    from src.api.routes.invoices import _sort_due_invoices

    invoices = [
        Invoice(id=4, due_date=None),
        Invoice(id=2, due_date=datetime(2026, 3, 1)),
        Invoice(id=1, due_date=None),
    ]
    ordered = _sort_due_invoices(invoices, {}, "due-date-asc")
    assert [invoice.id for invoice in ordered] == [2, 1, 4]
