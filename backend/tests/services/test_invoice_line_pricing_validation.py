"""Schema validation for invoice line pricing (issue #525).

Pydantic only, no database: FastAPI turns these ValidationErrors into
422 responses that name the offending field, which is exactly the
acceptance behaviour for POST /api/invoices/.
"""

import pytest
from pydantic import ValidationError

from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate


def _item(**overrides):
    values = {
        "product_id": 1,
        "quantity": 1,
        "unit_price": 100,
    }
    values.update(overrides)
    return InvoiceItemCreate(**values)


def _invoice(**overrides):
    values = {
        "ledger_id": 1,
        "items": [_item()],
    }
    values.update(overrides)
    return InvoiceCreate(**values)


def test_percentage_line_discount_over_100_rejected():
    with pytest.raises(ValidationError) as excinfo:
        _item(discount_type="percentage", discount_value=150)
    assert "discount_value" in str(excinfo.value)



@pytest.mark.parametrize("gst_rate", [-5, 101, -100])
def test_invoice_line_gst_rate_outside_zero_to_100_rejected(gst_rate):
    with pytest.raises(ValidationError) as excinfo:
        _item(gst_rate=gst_rate)
    assert "gst_rate" in str(excinfo.value)


@pytest.mark.parametrize("gst_rate", [0, 18, 100])
def test_invoice_line_gst_rate_in_range_accepted(gst_rate):
    assert _item(gst_rate=gst_rate).gst_rate == gst_rate


def test_invoice_line_gst_rate_override_can_be_omitted():
    assert _item().gst_rate is None


@pytest.mark.parametrize("hsn_sac", ["123", "12345", "12AB", "1234567", "123456789"])
def test_invalid_invoice_line_hsn_sac_rejected(hsn_sac):
    with pytest.raises(ValidationError) as excinfo:
        _item(hsn_sac=hsn_sac)
    assert "hsn_sac" in str(excinfo.value)


@pytest.mark.parametrize("hsn_sac", ["8482", "123456", "12345678"])
def test_valid_invoice_line_hsn_sac_accepted(hsn_sac):
    assert _item(hsn_sac=hsn_sac).hsn_sac == hsn_sac


def test_invoice_line_hsn_sac_is_normalized():
    assert _item(hsn_sac=" 8482 ").hsn_sac == "8482"


@pytest.mark.parametrize("hsn_sac", [None, "", "   "])
def test_invoice_line_hsn_sac_can_be_omitted(hsn_sac):
    assert _item(hsn_sac=hsn_sac).hsn_sac is None

def test_negative_unit_price_rejected():
    with pytest.raises(ValidationError) as excinfo:
        _item(unit_price=-5)
    assert "unit_price" in str(excinfo.value)


def test_negative_line_discount_rejected():
    with pytest.raises(ValidationError) as excinfo:
        _item(discount_type="net", discount_value=-10)
    assert "discount_value" in str(excinfo.value)


def test_percentage_invoice_discount_over_100_rejected():
    with pytest.raises(ValidationError) as excinfo:
        _invoice(discount_type="percentage", discount_value=150)
    assert "discount_value" in str(excinfo.value)


def test_negative_invoice_discount_rejected():
    with pytest.raises(ValidationError) as excinfo:
        _invoice(discount_type="net", discount_value=-1)
    assert "discount_value" in str(excinfo.value)


def test_zero_unit_price_still_accepted():
    assert _item(unit_price=0).unit_price == 0


def test_full_percentage_discount_still_accepted():
    item = _item(discount_type="percentage", discount_value=100)
    assert item.discount_value == 100


def test_net_discount_over_100_still_accepted():
    # A flat discount has no percentage cap; the processor clamps it to
    # the line total, so it must keep passing schema validation.
    item = _item(discount_type="net", discount_value=1000)
    assert item.discount_value == 1000


def test_discount_without_type_only_needs_non_negative():
    assert _item(discount_value=50).discount_value == 50
    assert _item(discount_value=None).discount_value is None
