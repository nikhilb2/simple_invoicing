import pytest
from pydantic import ValidationError

from src.schemas.invoice import InvoiceItemCreate


@pytest.mark.parametrize("product_id", [0, -1])
def test_line_without_a_picked_product_is_rejected_with_a_clear_message(product_id):
    with pytest.raises(ValidationError) as exc:
        InvoiceItemCreate(product_id=product_id, quantity=1)
    assert "Choose a product from the list for every line." in str(exc.value)


def test_line_with_a_product_is_accepted():
    assert InvoiceItemCreate(product_id=7, quantity=1).product_id == 7
