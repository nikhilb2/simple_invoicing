"""
Unit tests for:
  - src.services.financial_year.get_fy_for_date
  - src.services.series._format_number  (invoice_date parameter)
  - src.services.series.generate_next_number  (invoice_date + active_financial_year_id)
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.api.routes.financial_years import _seed_series_for_fy
from src.services.financial_year import get_fy_for_date
from src.services.series import _format_number, generate_next_number
from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_fy(id: int, label: str, start: date, end: date, is_active: bool = False) -> FinancialYear:
    fy = FinancialYear()
    fy.id = id
    fy.label = label
    fy.start_date = start
    fy.end_date = end
    fy.is_active = is_active
    return fy


def make_series(
    id: int,
    voucher_type: str = "sales",
    financial_year_id: int | None = None,
    prefix: str = "INV",
    suffix: str = "",
    include_year: bool = True,
    year_format: str = "FY",
    separator: str = "-",
    next_sequence: int = 1,
    pad_digits: int = 3,
) -> InvoiceSeries:
    s = InvoiceSeries()
    s.id = id
    s.voucher_type = voucher_type
    s.financial_year_id = financial_year_id
    s.prefix = prefix
    s.suffix = suffix
    s.include_year = include_year
    s.year_format = year_format
    s.separator = separator
    s.next_sequence = next_sequence
    s.pad_digits = pad_digits
    return s


class TestSeedSeriesForFy:
    def test_seeds_all_default_voucher_types_when_no_active_fy(self):
        db = MagicMock()

        with patch("src.api.routes.financial_years.get_active_fy", return_value=None):
            _seed_series_for_fy(db, new_fy_id=77)

        added = [call.args[0] for call in db.add.call_args_list]
        assert [row.voucher_type for row in added] == ["sales", "purchase", "payment"]
        assert all(row.financial_year_id == 77 for row in added)
        assert all(row.next_sequence == 1 for row in added)
        assert all(row.suffix == "" for row in added)

    def test_clones_series_config_and_resets_sequence(self):
        db = MagicMock()
        active_fy = make_fy(10, "2025-26", date(2025, 4, 1), date(2026, 3, 31), is_active=True)
        source_rows = [
            make_series(1, voucher_type="sales", financial_year_id=10, prefix="RES", suffix="-A", year_format="FY", next_sequence=12, pad_digits=4),
            make_series(2, voucher_type="purchase", financial_year_id=10, prefix="PUR", suffix="", include_year=False, next_sequence=8, pad_digits=2),
            make_series(3, voucher_type="payment", financial_year_id=10, prefix="PAY", suffix="/RCPT", year_format="YYYY", next_sequence=3, pad_digits=3),
        ]
        db.query().filter().all.return_value = source_rows

        with patch("src.api.routes.financial_years.get_active_fy", return_value=active_fy):
            _seed_series_for_fy(db, new_fy_id=88)

        added = [call.args[0] for call in db.add.call_args_list]
        assert len(added) == 3

        sales = next(row for row in added if row.voucher_type == "sales")
        assert sales.prefix == "RES"
        assert sales.suffix == "-A"
        assert sales.year_format == "FY"
        assert sales.next_sequence == 1
        assert sales.pad_digits == 4

        purchase = next(row for row in added if row.voucher_type == "purchase")
        assert purchase.include_year is False
        assert purchase.next_sequence == 1

        payment = next(row for row in added if row.voucher_type == "payment")
        assert payment.suffix == "/RCPT"
        assert payment.next_sequence == 1

    def test_backfills_missing_voucher_type_from_defaults(self):
        db = MagicMock()
        active_fy = make_fy(10, "2025-26", date(2025, 4, 1), date(2026, 3, 31), is_active=True)
        db.query().filter().all.return_value = [
            make_series(1, voucher_type="sales", financial_year_id=10, prefix="SLS", suffix="-NEW", year_format="FY"),
            make_series(2, voucher_type="purchase", financial_year_id=10, prefix="BUY", include_year=False),
        ]

        with patch("src.api.routes.financial_years.get_active_fy", return_value=active_fy):
            _seed_series_for_fy(db, new_fy_id=99)

        added = [call.args[0] for call in db.add.call_args_list]
        payment = next(row for row in added if row.voucher_type == "payment")
        assert payment.prefix == "PAY"
        assert payment.suffix == ""
        assert payment.include_year is True
        assert payment.year_format == "YYYY"
        assert payment.next_sequence == 1


# ─────────────────────────────────────────────────────────────────────────────
# get_fy_for_date
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFyForDate:
    def _db(self, result):
        """Return a mock db whose filter chain returns `result`."""
        db = MagicMock()
        db.query().filter().first.return_value = result
        return db

    def test_returns_matching_fy(self):
        fy = make_fy(1, "2025-26", date(2025, 4, 1), date(2026, 3, 31))
        db = self._db(fy)
        assert get_fy_for_date(db, date(2025, 10, 15)) is fy

    def test_returns_none_when_no_match(self):
        db = self._db(None)
        assert get_fy_for_date(db, date(2020, 1, 1)) is None

    def test_boundary_start_date(self):
        fy = make_fy(1, "2025-26", date(2025, 4, 1), date(2026, 3, 31))
        db = self._db(fy)
        assert get_fy_for_date(db, date(2025, 4, 1)) is fy

    def test_boundary_end_date(self):
        fy = make_fy(1, "2025-26", date(2025, 4, 1), date(2026, 3, 31))
        db = self._db(fy)
        assert get_fy_for_date(db, date(2026, 3, 31)) is fy


# ─────────────────────────────────────────────────────────────────────────────
# _format_number — invoice_date threading
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatNumber:
    def test_fy_format_uses_fy_label(self):
        fy = make_fy(1, "2025-26", date(2025, 4, 1), date(2026, 3, 31))
        s = make_series(1, year_format="FY")
        assert _format_number(s, 1, fy) == "INV-2025-26-001"

    def test_appends_suffix_without_extra_separator(self):
        fy = make_fy(1, "2025-26", date(2025, 4, 1), date(2026, 3, 31))
        s = make_series(1, year_format="FY", suffix="/A")
        assert _format_number(s, 1, fy) == "INV-2025-26-001/A"

    def test_fy_format_fallback_when_no_fy(self):
        s = make_series(1, year_format="FY")
        assert _format_number(s, 1, None) == "INV-FY-001"

    def test_yyyy_uses_invoice_date_year(self):
        s = make_series(1, year_format="YYYY")
        result = _format_number(s, 5, None, invoice_date=date(2025, 12, 1))
        assert result == "INV-2025-005"

    def test_yyyy_falls_back_to_today_when_no_date(self):
        s = make_series(1, year_format="YYYY")
        today_year = str(date.today().year)
        result = _format_number(s, 1, None, invoice_date=None)
        assert today_year in result

    def test_mm_yyyy_uses_invoice_date_month_and_year(self):
        s = make_series(1, year_format="MM-YYYY")
        result = _format_number(s, 3, None, invoice_date=date(2025, 12, 15))
        assert result == "INV-12-2025-003"

    def test_mm_yyyy_january(self):
        s = make_series(1, year_format="MM-YYYY")
        result = _format_number(s, 1, None, invoice_date=date(2026, 1, 1))
        assert result == "INV-01-2026-001"

    def test_no_year_format(self):
        s = make_series(1, include_year=False)
        result = _format_number(s, 7, None, invoice_date=date(2025, 6, 1))
        assert result == "INV-007"

    def test_no_year_format_with_suffix(self):
        s = make_series(1, include_year=False, suffix="-TAIL")
        result = _format_number(s, 7, None, invoice_date=date(2025, 6, 1))
        assert result == "INV-007-TAIL"

    def test_custom_separator_and_padding(self):
        s = make_series(1, year_format="YYYY", separator="/", pad_digits=4)
        result = _format_number(s, 2, None, invoice_date=date(2025, 4, 1))
        assert result == "INV/2025/0002"


# ─────────────────────────────────────────────────────────────────────────────
# generate_next_number — FY-date and format-borrowing
# ─────────────────────────────────────────────────────────────────────────────

def _make_db_for_generate(
    target_series: InvoiceSeries | None,
    active_series: InvoiceSeries | None = None,
    linked_fy: FinancialYear | None = None,
    existing_numbers: set[str] | None = None,
):
    """
    Build a mock db suitable for generate_next_number.

    Query routing (in order of appearance in generate_next_number):
      1. InvoiceSeries (with_for_update) for target FY       → target_series
      2. InvoiceSeries (with_for_update) for NULL fallback    → only reached if target is None
      3. InvoiceSeries for active FY format borrowing         → active_series
      4. FinancialYear for FY label                           → linked_fy
      5. Invoice for duplicate check                          → None (no collision)
    """
    # series_call_count is in _make_db_for_generate scope so that all
    # db.query(InvoiceSeries) calls share the same counter via closure.
    series_call_count = {"n": 0}

    def query_side_effect(model):
        from src.models.invoice import Invoice  # noqa: PLC0415

        mock_q = MagicMock()

        if model is InvoiceSeries:
            def filter_side(*args, **kwargs):
                series_call_count["n"] += 1
                inner = MagicMock()
                with_update = MagicMock()

                if series_call_count["n"] == 1:
                    # First call: target FY series lookup (with_for_update path)
                    with_update.first.return_value = target_series
                    inner.with_for_update.return_value = with_update
                    inner.first.return_value = target_series
                elif series_call_count["n"] == 2 and target_series is None:
                    # Second call: NULL fy_id fallback (only when target not found)
                    with_update.first.return_value = None
                    inner.with_for_update.return_value = with_update
                    inner.first.return_value = None
                else:
                    # Active FY format-borrowing lookup
                    inner.first.return_value = active_series

                return inner

            mock_q.filter.side_effect = filter_side

        elif model is FinancialYear:
            inner = MagicMock()
            inner.first.return_value = linked_fy
            mock_q.filter.return_value = inner

        else:
            # Invoice duplicate check — always returns None (no collision)
            inner = MagicMock()
            inner.first.return_value = None
            mock_q.filter.return_value = inner

        return mock_q

    db = MagicMock()
    db.query.side_effect = query_side_effect
    return db


class TestGenerateNextNumber:
    def test_returns_fallback_when_no_series(self):
        db = MagicMock()
        # Both series lookups return None
        mock_q = MagicMock()
        mock_q.filter.return_value.with_for_update.return_value.first.return_value = None
        mock_q.filter.return_value.first.return_value = None
        db.query.return_value = mock_q
        result = generate_next_number(db, "sales")
        assert result == "INV-000000"

    def test_basic_fy_format_within_active_fy(self):
        """Generating for the active FY uses the target series + target FY label."""
        fy = make_fy(10, "2025-26", date(2025, 4, 1), date(2026, 3, 31), is_active=True)
        target = make_series(1, financial_year_id=10, year_format="FY")

        db = _make_db_for_generate(target_series=target, linked_fy=fy)
        result = generate_next_number(
            db,
            "sales",
            financial_year_id=10,
            active_financial_year_id=10,
        )
        assert result == "INV-2025-26-001"
        assert target.next_sequence == 2

    def test_backdated_borrows_active_fy_format_settings(self):
        """
        When financial_year_id != active_financial_year_id, format settings
        come from the active FY's series, but the counter and FY label come
        from the target FY.
        """
        past_fy = make_fy(9, "2024-25", date(2024, 4, 1), date(2025, 3, 31))
        active_fy = make_fy(10, "2025-26", date(2025, 4, 1), date(2026, 3, 31), is_active=True)

        # Past FY series has stale MM-YYYY format (seeded before user changed it)
        target = make_series(1, financial_year_id=9, prefix="OLD", year_format="MM-YYYY")
        # Active FY series has the user-configured FY format
        active = make_series(2, financial_year_id=10, prefix="RES", year_format="FY")

        db = _make_db_for_generate(
            target_series=target,
            active_series=active,
            linked_fy=past_fy,  # label for the TARGET (past) FY
        )
        result = generate_next_number(
            db,
            "sales",
            financial_year_id=9,
            active_financial_year_id=10,
        )
        # Format from active series (RES, FY), label from past FY (2024-25),
        # sequence from past series
        assert result == "RES-2024-25-001"
        assert target.next_sequence == 2  # counter incremented on target series

    def test_invoice_date_used_in_yyyy_format(self):
        """invoice_date determines the YYYY part, not today's date."""
        target = make_series(1, financial_year_id=10, year_format="YYYY")
        db = _make_db_for_generate(target_series=target)

        result = generate_next_number(
            db,
            "sales",
            financial_year_id=10,
            invoice_date=date(2024, 12, 15),
            active_financial_year_id=10,
        )
        assert result == "INV-2024-001"

    def test_invoice_date_used_in_mm_yyyy_format(self):
        """invoice_date determines MM-YYYY, not the current month."""
        target = make_series(1, financial_year_id=10, year_format="MM-YYYY")
        db = _make_db_for_generate(target_series=target)

        result = generate_next_number(
            db,
            "sales",
            financial_year_id=10,
            invoice_date=date(2025, 7, 4),
            active_financial_year_id=10,
        )
        assert result == "INV-07-2025-001"

    def test_no_active_fy_id_uses_target_series_format(self):
        """When active_financial_year_id is None, no format borrowing occurs."""
        fy = make_fy(10, "2025-26", date(2025, 4, 1), date(2026, 3, 31))
        target = make_series(1, financial_year_id=10, year_format="FY")
        db = _make_db_for_generate(target_series=target, linked_fy=fy)

        result = generate_next_number(
            db,
            "sales",
            financial_year_id=10,
            active_financial_year_id=None,
        )
        assert result == "INV-2025-26-001"

    def test_counter_increments_on_target_series_not_active(self):
        """The counter must advance on the TARGET series, never the active one."""
        past_fy = make_fy(9, "2024-25", date(2024, 4, 1), date(2025, 3, 31))
        target = make_series(1, financial_year_id=9, year_format="FY", next_sequence=5)
        active = make_series(2, financial_year_id=10, prefix="RES", year_format="FY", next_sequence=1)

        db = _make_db_for_generate(
            target_series=target, active_series=active, linked_fy=past_fy
        )
        generate_next_number(
            db, "sales", financial_year_id=9, active_financial_year_id=10
        )
        assert target.next_sequence == 6
        assert active.next_sequence == 1  # untouched

    def test_generate_next_number_applies_suffix(self):
        fy = make_fy(10, "2025-26", date(2025, 4, 1), date(2026, 3, 31), is_active=True)
        target = make_series(1, financial_year_id=10, year_format="FY", suffix="/S")

        db = _make_db_for_generate(target_series=target, linked_fy=fy)
        result = generate_next_number(
            db,
            "sales",
            financial_year_id=10,
            active_financial_year_id=10,
        )
        assert result == "INV-2025-26-001/S"
