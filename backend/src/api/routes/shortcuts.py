from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ShortcutBinding(BaseModel):
    ctrlOrCmd: bool
    shift: bool
    alt: bool
    key: str


class ShortcutDefinition(BaseModel):
    action: str
    label: str
    binding: ShortcutBinding


_DEFAULT_SHORTCUTS: list[ShortcutDefinition] = [
    ShortcutDefinition(
        action="submit_invoice",
        label="Submit invoice",
        binding=ShortcutBinding(ctrlOrCmd=True, shift=False, alt=False, key="Enter"),
    ),
    ShortcutDefinition(
        action="add_line_item",
        label="Add line item",
        binding=ShortcutBinding(ctrlOrCmd=False, shift=True, alt=False, key="A"),
    ),
    ShortcutDefinition(
        action="add_ledger",
        label="Add ledger",
        binding=ShortcutBinding(ctrlOrCmd=False, shift=True, alt=False, key="L"),
    ),
    ShortcutDefinition(
        action="add_product",
        label="Add product",
        binding=ShortcutBinding(ctrlOrCmd=False, shift=True, alt=False, key="P"),
    ),
    ShortcutDefinition(
        action="update_stock",
        label="Update stock",
        binding=ShortcutBinding(ctrlOrCmd=False, shift=True, alt=False, key="S"),
    ),
    ShortcutDefinition(
        action="toggle_help",
        label="Toggle help",
        binding=ShortcutBinding(ctrlOrCmd=True, shift=False, alt=False, key="/"),
    ),
]


@router.get("")
@router.get("/")
def list_shortcuts():
    return {"shortcuts": _DEFAULT_SHORTCUTS}
