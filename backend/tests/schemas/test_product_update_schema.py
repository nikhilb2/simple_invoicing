"""Schema-level tests for ProductWithInventoryUpdate (issue #667)."""

import pytest
from pydantic import ValidationError

from src.schemas.product import ProductWithInventoryUpdate


def _update(**fields) -> ProductWithInventoryUpdate:
    return ProductWithInventoryUpdate(**fields)


def test_blank_unit_is_rejected():
    with pytest.raises(ValidationError):
        _update(unit="   ")


def test_unit_is_stripped():
    assert _update(unit="  kg  ").unit == "kg"


def test_unit_none_untouched():
    assert _update(unit=None).unit is None


def test_unknown_status_is_rejected():
    with pytest.raises(ValidationError):
        _update(status="archived")


def test_known_statuses_are_accepted():
    assert _update(status="active").status == "active"
    assert _update(status="inactive").status == "inactive"
