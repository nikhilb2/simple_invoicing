# ruff: noqa: EXE002
import sys
import types
from datetime import UTC, date, datetime
from types import SimpleNamespace

# Ensure optional external dependencies do not block testing in environments missing system libraries
if "weasyprint" not in sys.modules:
    sys.modules["weasyprint"] = types.ModuleType("weasyprint")

from src.services.series import _format_number


def test_format_number_without_year():
    """When include_year is False, format is {prefix}{sep}{seq_str}{suffix}."""
    series = SimpleNamespace(
        prefix="INV",
        separator="-",
        pad_digits=4,
        suffix=None,
        include_year=False,
        year_format="FY",
    )
    result = _format_number(series, seq=1, fy=None)
    assert result == "INV-0001"

    # With suffix
    series.suffix = "-DRAFT"
    result = _format_number(series, seq=42, fy=None)
    assert result == "INV-0042-DRAFT"

    # Different separator and higher sequence
    series.separator = "/"
    series.suffix = ""
    series.pad_digits = 5
    result = _format_number(series, seq=123, fy=None)
    assert result == "INV/00123"


def test_format_number_without_year_overflow_digits():
    """Sequence number longer than pad_digits is preserved without truncation."""
    series = SimpleNamespace(
        prefix="REC",
        separator="-",
        pad_digits=3,
        suffix=None,
        include_year=False,
        year_format="FY",
    )
    result = _format_number(series, seq=12345, fy=None)
    assert result == "REC-12345"


def test_format_number_year_format_fy():
    """year_format == 'FY' uses financial year label, or falls back to 'FY' when fy is None."""
    series = SimpleNamespace(
        prefix="INV",
        separator="-",
        pad_digits=4,
        suffix=None,
        include_year=True,
        year_format="FY",
    )
    fy = SimpleNamespace(label="2025-26")

    # With FinancialYear instance / SimpleNamespace
    result = _format_number(series, seq=1, fy=fy)
    assert result == "INV-2025-26-0001"

    # With suffix and different sequence
    series.suffix = "/GST"
    result = _format_number(series, seq=99, fy=fy)
    assert result == "INV-2025-26-0099/GST"

    # Fallback to "FY" when fy is None
    series.suffix = None
    result_none_fy = _format_number(series, seq=1, fy=None)
    assert result_none_fy == "INV-FY-0001"


def test_format_number_year_format_mm_yyyy_with_date():
    """year_format == 'MM-YYYY' with explicit invoice_date formats month and 4-digit year."""
    series = SimpleNamespace(
        prefix="INV",
        separator="-",
        pad_digits=4,
        suffix=None,
        include_year=True,
        year_format="MM-YYYY",
    )
    inv_date = date(2026, 3, 15)

    result = _format_number(series, seq=7, fy=None, invoice_date=inv_date)
    assert result == "INV-03-2026-0007"

    # With slash separator
    series.separator = "/"
    result_slash = _format_number(series, seq=12, fy=None, invoice_date=inv_date)
    assert result_slash == "INV/03/2026/0012"


def test_format_number_year_format_mm_yyyy_fallback_today():
    """year_format == 'MM-YYYY' with invoice_date=None falls back to current date."""
    series = SimpleNamespace(
        prefix="BILL",
        separator="-",
        pad_digits=4,
        suffix=None,
        include_year=True,
        year_format="MM-YYYY",
    )
    today = datetime.now(UTC).date()
    expected_year_part = f"{today.strftime('%m')}-{today.year}"

    result = _format_number(series, seq=1, fy=None, invoice_date=None)
    assert result == f"BILL-{expected_year_part}-0001"


def test_format_number_year_format_other_or_yyyy():
    """Any year_format other than 'FY' or 'MM-YYYY' uses the 4-digit year."""
    series = SimpleNamespace(
        prefix="INV",
        separator="-",
        pad_digits=3,
        suffix=None,
        include_year=True,
        year_format="YYYY",
    )
    inv_date = date(2026, 7, 20)

    result = _format_number(series, seq=5, fy=None, invoice_date=inv_date)
    assert result == "INV-2026-005"

    # Arbitrary other year_format string defaults to 4-digit year
    series.year_format = "standard"
    series.suffix = "-TX"
    result_other = _format_number(series, seq=5, fy=None, invoice_date=inv_date)
    assert result_other == "INV-2026-005-TX"


def test_format_number_year_format_other_fallback_today():
    """Other year_format with invoice_date=None uses current year."""
    series = SimpleNamespace(
        prefix="INV",
        separator="-",
        pad_digits=4,
        suffix=None,
        include_year=True,
        year_format="YYYY",
    )
    today_year = datetime.now(UTC).date().year

    result = _format_number(series, seq=1, fy=None, invoice_date=None)
    assert result == f"INV-{today_year}-0001"
