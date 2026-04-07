import json
from pathlib import Path

from src.core.config import settings
from pydantic import BaseModel


class ShortcutAction(BaseModel):
    key: str
    label: str
    kind: str
    path: str | None = None
    description: str


SHORTCUTS: list[ShortcutAction] = [
    ShortcutAction(
        key="open-dashboard",
        label="Open Dashboard",
        kind="navigate",
        path="/",
        description="Jump to the main dashboard.",
    ),
    ShortcutAction(
        key="open-invoices",
        label="Open Invoices",
        kind="navigate",
        path="/invoices",
        description="Open the invoices workspace.",
    ),
    ShortcutAction(
        key="open-products",
        label="Open Products",
        kind="navigate",
        path="/products",
        description="Open the product catalog.",
    ),
    ShortcutAction(
        key="open-inventory",
        label="Open Inventory",
        kind="navigate",
        path="/inventory",
        description="Open the inventory screen.",
    ),
    ShortcutAction(
        key="open-ledgers",
        label="Open Ledgers",
        kind="navigate",
        path="/ledgers",
        description="Open the ledger list.",
    ),
    ShortcutAction(
        key="new-ledger",
        label="New Ledger",
        kind="navigate",
        path="/ledgers/new",
        description="Start a new ledger entry.",
    ),
    ShortcutAction(
        key="open-day-book",
        label="Open Day Book",
        kind="navigate",
        path="/day-book",
        description="Open the daily book view.",
    ),
    ShortcutAction(
        key="open-company",
        label="Open Company",
        kind="navigate",
        path="/company",
        description="Open company settings.",
    ),
    ShortcutAction(
        key="open-smtp-settings",
        label="Open SMTP Settings",
        kind="navigate",
        path="/smtp-settings",
        description="Open email configuration for admins.",
    ),
]


def load_shortcuts() -> list[ShortcutAction]:
    config_path = settings.SHORTCUTS_CONFIG_PATH
    if config_path:
        path = Path(config_path)
    else:
        path = Path(__file__).with_name("shortcuts.json")

    if not path.exists():
        return SHORTCUTS

    try:
        raw_shortcuts = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return SHORTCUTS

    parsed: list[ShortcutAction] = []
    for item in raw_shortcuts:
        try:
            parsed.append(ShortcutAction.model_validate(item))
        except Exception:
            continue

    return parsed or SHORTCUTS
