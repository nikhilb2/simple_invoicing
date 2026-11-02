"""Shared setup for the quotation tests."""

from datetime import date

GST_MH = "27AADCB2230M1ZT"
GST_KA = "29AADCB2230M1ZP"


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json()


def seed_financial_year(client) -> dict:
    """A year wide enough for the back-dated documents these tests write, with its series."""
    today = date.today()
    fy = ok(client.post("/api/financial-years/", json={
        "label": "TEST-FY",
        "start_date": date(today.year - 1, 1, 1).isoformat(),
        "end_date": date(today.year + 1, 12, 31).isoformat(),
    }), 201)
    return ok(client.put(f"/api/financial-years/{fy['id']}/activate"))


def seed_company(client, *, gst: str = GST_MH, currency: str = "INR") -> dict:
    company = ok(client.put("/api/company/", json={
        "name": "Acme Traders",
        "address": "1 Market Road",
        "gst": gst,
        "phone_number": "9876543210",
        "currency_code": currency,
        "email": "hello@acme.example",
        "website": "",
        "bank_name": "Snapshot Bank",
        "branch_name": "Fort",
        "account_name": "Acme Traders",
        "account_number": "000111222",
        "ifsc_code": "SNAP0001",
    }))
    seed_financial_year(client)
    return company


def create_ledger(client, name: str = "Customer One", gst: str = GST_MH) -> dict:
    return ok(client.post("/api/ledgers/", json={
        "name": name,
        "address": "2 Buyer Street",
        "gst": gst,
        "opening_balance": None,
        "phone_number": "9000000000",
        "email": "",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }))


def create_product(client, sku: str = "WID-1", **overrides) -> dict:
    body = {
        "sku": sku,
        "name": f"Widget {sku}",
        "hsn_sac": "84713010",
        "price": 100,
        "gst_rate": 18,
        "maintain_inventory": True,
        "initial_quantity": 100,
    }
    body.update(overrides)
    return ok(client.post("/api/products/", json=body))


def quotation_payload(ledger_id: int, product_id: int, *, document_type: str = "quotation", quantity=2, **extra) -> dict:
    body = {
        "document_type": document_type,
        "ledger_id": ledger_id,
        "items": [{"product_id": product_id, "quantity": quantity, "unit_price": 100}],
    }
    body.update(extra)
    return body


def create_quotation(client, ledger_id: int, product_id: int, **kwargs) -> dict:
    return ok(client.post("/api/quotations/", json=quotation_payload(ledger_id, product_id, **kwargs)))


def convert(client, quotation_id: int, **overrides):
    draft = ok(client.get(f"/api/quotations/{quotation_id}/conversion-draft"))
    # The draft's invoice is what the composer opens with and posts back.
    payload = draft["invoice"]
    payload.update(overrides)
    return client.post(f"/api/quotations/{quotation_id}/convert", json=payload)


def series_counters(client) -> dict[str, int]:
    return {row["voucher_type"]: row["next_sequence"] for row in ok(client.get("/api/invoice-series/"))}


def iso_today() -> str:
    return date.today().isoformat()
