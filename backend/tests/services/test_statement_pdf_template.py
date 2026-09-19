"""Unit tests for the ledger statement PDF HTML template.

The statement preview in the frontend is now the backend PDF itself, so the
template is the single source of truth for what a statement says — these cover
the header/ledger contact lines and the voucher-number fallback, the fields the
old hand-written JSX rendered and the template did not.

The same `_build_statement_html` backs the authenticated download, the public
share page and the emailed statement, so a gap here shows up in all three.
"""

from datetime import date, datetime

from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.schemas.ledger import LedgerStatementEntry
from src.services.pdf_templates.ledger_template import _build_statement_html


def make_company(**overrides) -> CompanyProfile:
    defaults = dict(
        id=1,
        name="Respawn Pvt Ltd",
        address="1 Billing Street",
        gst="29RESP1234N1Z1",
        phone_number="9999999999",
        email="accounts@respawn.in",
        website="https://respawn.in",
        currency_code="INR",
    )
    defaults.update(overrides)
    return CompanyProfile(**defaults)


def make_ledger(**overrides) -> Ledger:
    defaults = dict(
        id=1,
        company_id=1,
        name="Acme Stores",
        address="42 Market Road",
        gst="29ABCDE1234F1Z5",
        phone_number="9899001009",
        email="books@acme.in",
    )
    defaults.update(overrides)
    return Ledger(**defaults)


def make_entry(**overrides) -> LedgerStatementEntry:
    defaults = dict(
        entry_id=17,
        entry_type="invoice",
        date=datetime(2025, 4, 13),
        voucher_type="Sales",
        reference_number="INV-2025-001",
        particulars="Acme Stores",
        debit=1000.0,
        credit=0.0,
    )
    defaults.update(overrides)
    return LedgerStatementEntry(**defaults)


def render(company=None, ledger=None, entries=None) -> str:
    return _build_statement_html(
        company=make_company() if company is None else company,
        ledger=make_ledger() if ledger is None else ledger,
        from_date=date(2025, 4, 1),
        to_date=date(2026, 3, 31),
        opening_balance=0.0,
        period_debit=1000.0,
        period_credit=0.0,
        closing_balance=1000.0,
        entries=[make_entry()] if entries is None else entries,
    )


class TestCompanyContactLine:
    def test_renders_company_email_and_website(self):
        html = render()
        assert "Email: accounts@respawn.in &middot; Web: https://respawn.in" in html

    def test_omits_the_separator_when_only_one_is_set(self):
        html = render(company=make_company(website=""))
        assert "Email: accounts@respawn.in" in html
        assert "Web:" not in html
        assert "accounts@respawn.in &middot;" not in html

    def test_emits_nothing_when_neither_is_set(self):
        html = render(company=make_company(email="", website=""))
        assert "Email:" not in html
        assert "Web:" not in html

    def test_escapes_the_contact_values(self):
        html = render(company=make_company(website="https://x.test/?a=1&b=2"))
        assert "https://x.test/?a=1&amp;b=2" in html


class TestLedgerDetailsLine:
    def test_appends_the_ledger_email(self):
        html = render()
        assert (
            "GST: 29ABCDE1234F1Z5 &middot; Phone: 9899001009 &middot; books@acme.in"
            in html
        )

    def test_omits_a_stray_separator_when_the_email_is_unset(self):
        html = render(ledger=make_ledger(email=None))
        assert "GST: 29ABCDE1234F1Z5 &middot; Phone: 9899001009" in html
        assert "9899001009 &middot; </p>" not in html

    def test_email_alone_carries_no_bare_gst_label(self):
        html = render(ledger=make_ledger(gst=None, phone_number=None))
        # The whole paragraph is the email — no leftover "GST: " or "Phone: ".
        assert ">books@acme.in</p>" in html


class TestVoucherNumberFallback:
    def test_uses_the_reference_number_when_present(self):
        html = render()
        assert "<td>INV-2025-001</td>" in html

    def test_falls_back_to_voucher_type_and_entry_id(self):
        html = render(entries=[make_entry(reference_number=None)])
        assert "<td>Sales #17</td>" in html

    def test_escapes_the_voucher_type_in_the_fallback(self):
        html = render(
            entries=[make_entry(reference_number=None, voucher_type="A & B")]
        )
        assert "<td>A &amp; B #17</td>" in html

    def test_fallback_has_no_leading_space_without_a_voucher_type(self):
        html = render(entries=[make_entry(reference_number=None, voucher_type="")])
        assert "<td>#17</td>" in html
