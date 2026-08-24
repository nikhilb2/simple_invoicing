"""Money and quantities must leave this API as decimal STRINGS.

The frontend parses them with exact decimal arithmetic and calls .trim() on
them, so a JSON number is not a cosmetic difference — it is an immediate
TypeError that takes the whole page down. This has now escaped twice: first on
the listings/orders schemas, then on the browse proxy, because each fix was
aimed at the endpoint that happened to crash.

So this test asserts over the schemas themselves rather than over a handful of
responses: any NEW money or quantity field is caught the moment it is declared
as a float, without anyone remembering to add a case here.
"""

import inspect
from decimal import Decimal

import pytest
from pydantic import BaseModel

from src.schemas import marketplace as schemas

#: Field names that carry money or quantity. Matched by suffix so variants like
#: available_quantity_published are covered without listing every one.
MONETARY_SUFFIXES = (
    "price", "amount", "quantity", "gst_rate", "total",
)


def _monetary_fields(model: type[BaseModel]):
    for name, field in model.model_fields.items():
        if any(name.endswith(suffix) for suffix in MONETARY_SUFFIXES):
            yield name, field


def _models():
    for _, obj in inspect.getmembers(schemas, inspect.isclass):
        if issubclass(obj, BaseModel) and obj is not BaseModel and obj.__module__ == schemas.__name__:
            yield obj


@pytest.mark.parametrize("model", sorted(_models(), key=lambda m: m.__name__))
def test_no_monetary_field_is_a_float(model):
    offenders = [
        name for name, field in _monetary_fields(model)
        if "float" in str(field.annotation)
    ]
    assert not offenders, (
        f"{model.__name__} declares monetary field(s) {offenders} as float. "
        "Use Decimal; response models additionally need a field_serializer "
        "emitting a string (see _money_str / _qty_str)."
    )


@pytest.mark.parametrize(
    "model_name",
    ["ListingOut", "BrowseListingOut", "OrderOut", "OrderItemOut", "ConnectionOut"],
)
def test_response_models_serialise_money_as_strings(model_name):
    """Decimal alone is not enough: pydantic serialises Decimal to a JSON number
    unless a serializer turns it into a string."""
    model = getattr(schemas, model_name)
    monetary = [name for name, _ in _monetary_fields(model)]
    if not monetary:
        pytest.skip(f"{model_name} carries no monetary fields")

    payload = {}
    for name, field in model.model_fields.items():
        if name in monetary:
            payload[name] = Decimal("1234.5")
        elif field.is_required():
            annotation = str(field.annotation)
            payload[name] = 1 if "int" in annotation else "x"

    dumped = model.model_construct(**payload).model_dump(mode="json")
    for name in monetary:
        assert isinstance(dumped[name], str), (
            f"{model_name}.{name} serialised as {type(dumped[name]).__name__}, "
            "expected a decimal string"
        )
