"""Navigation shortcuts can be listed, customised, and reset independently."""

import re
from pathlib import Path

import pytest

from src.api.routes.shortcuts import DEFAULTS
from src.models.user import User, UserRole
from src.models.user_shortcut import UserShortcut


@pytest.fixture
def saved_shortcut(db_session):
    user = User(
        id=1,
        email="shortcuts@example.com",
        full_name="Shortcut Tester",
        hashed_password="unused",
        role=UserRole.admin,
    )
    shortcut = UserShortcut(
        user_id=1, action_key="go_invoices", shortcut_key="Alt+X"
    )
    db_session.add_all([user, shortcut])
    db_session.commit()


def shortcut_map(client):
    response = client.get("/api/shortcuts/")
    assert response.status_code == 200
    return {
        entry["action_key"]: entry["shortcut_key"]
        for entry in response.json()["shortcuts"]
    }


@pytest.mark.parametrize(
    "action_key,default_key",
    [
        ("go_invoice_dues", "Alt+U"),
        ("go_credit_notes", "Alt+N"),
        ("go_gstr1", "Alt+G"),
        ("go_dashboard", "Alt+O"),
    ],
)
def test_navigation_shortcut_can_be_customised_and_reset(
    client, saved_shortcut, action_key, default_key
):
    defaults = shortcut_map(client)
    assert defaults.get(action_key) == default_key
    assert defaults["go_invoices"] == "Alt+X"

    response = client.put(
        f"/api/shortcuts/{action_key}", json={"shortcut_key": "Alt+Z"}
    )
    assert response.status_code == 200
    assert response.json() == {"action_key": action_key, "shortcut_key": "Alt+Z"}
    custom = shortcut_map(client)
    assert custom[action_key] == "Alt+Z"
    assert custom["go_invoices"] == "Alt+X"

    response = client.delete(f"/api/shortcuts/{action_key}")
    assert response.status_code == 204
    reset = shortcut_map(client)
    assert reset[action_key] == default_key
    assert reset["go_invoices"] == "Alt+X"


# The frontend carries its own copy of the defaults. The backend list is what
# the shortcuts API returns, so a key missing from it never reaches the page
# (go_tax_ledger was exactly that), and a key left behind (go_inventory) shows
# up as an action nothing handles. Comparing the two files catches both.
FRONTEND_DEFAULTS = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "utils" / "shortcutDefaults.ts"
)


def _frontend_default_shortcuts():
    if not FRONTEND_DEFAULTS.exists():
        pytest.skip(f"frontend shortcut defaults not found at {FRONTEND_DEFAULTS}")
    source = FRONTEND_DEFAULTS.read_text(encoding="utf-8")
    block = re.search(r"DEFAULT_SHORTCUTS[^=]*=\s*\{(.*?)\}", source, re.DOTALL)
    assert block, "could not find DEFAULT_SHORTCUTS in shortcutDefaults.ts"
    parsed = dict(re.findall(r"(\w+)\s*:\s*'([^']+)'", block.group(1)))
    # A changed file layout must fail loudly rather than compare against nothing.
    assert len(parsed) >= 10, f"parsed too few frontend shortcuts: {sorted(parsed)}"
    return parsed


def test_backend_default_shortcuts_have_the_same_actions_as_the_frontend():
    frontend = _frontend_default_shortcuts()

    assert set(DEFAULTS) == set(frontend), (
        f"missing from backend: {sorted(set(frontend) - set(DEFAULTS))}, "
        f"only in backend: {sorted(set(DEFAULTS) - set(frontend))}"
    )


def test_backend_default_shortcuts_have_the_same_keys_as_the_frontend():
    assert DEFAULTS == _frontend_default_shortcuts()
