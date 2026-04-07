from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.db.session import get_db
from src.models.user import User
from src.models.user_shortcut import UserShortcut
from src.schemas.user_shortcut import (
    UserShortcutResponse,
    UserShortcutUpdate,
    UserShortcutsListResponse,
)

DEFAULTS: dict[str, str] = {
    "create_invoice": "Ctrl+N",
    "save_invoice":   "Ctrl+S",
    "open_search":    "Ctrl+F",
    "open_reports":   "Ctrl+R",
    "new_customer":   "Ctrl+Shift+C",
    "go_invoices":    "Alt+I",
    "go_ledgers":     "Alt+L",
    "go_products":    "Alt+P",
    "go_inventory":   "Alt+V",
    "go_day_book":    "Alt+D",
}

router = APIRouter()


@router.get("", response_model=UserShortcutsListResponse, include_in_schema=False)
@router.get("/", response_model=UserShortcutsListResponse)
def list_shortcuts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserShortcutsListResponse:
    user_rows = db.query(UserShortcut).filter(UserShortcut.user_id == current_user.id).all()
    custom: dict[str, str] = {row.action_key: row.shortcut_key for row in user_rows}
    merged = [
        UserShortcutResponse(action_key=action_key, shortcut_key=custom.get(action_key, default_key))
        for action_key, default_key in DEFAULTS.items()
    ]
    return UserShortcutsListResponse(shortcuts=merged)


@router.put("/{action_key}", response_model=UserShortcutResponse)
def upsert_shortcut(
    action_key: str,
    payload: UserShortcutUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserShortcutResponse:
    if action_key not in DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unknown action key: {action_key}")

    row = (
        db.query(UserShortcut)
        .filter(UserShortcut.user_id == current_user.id, UserShortcut.action_key == action_key)
        .first()
    )
    if row:
        row.shortcut_key = payload.shortcut_key
    else:
        row = UserShortcut(
            user_id=current_user.id,
            action_key=action_key,
            shortcut_key=payload.shortcut_key,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return UserShortcutResponse(action_key=row.action_key, shortcut_key=row.shortcut_key)


@router.delete("/{action_key}", status_code=204)
def delete_shortcut(
    action_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    row = (
        db.query(UserShortcut)
        .filter(UserShortcut.user_id == current_user.id, UserShortcut.action_key == action_key)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No custom shortcut found for this action")
    db.delete(row)
    db.commit()


@router.delete("", status_code=204, include_in_schema=False)
@router.delete("/", status_code=204)
def delete_all_shortcuts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    db.query(UserShortcut).filter(UserShortcut.user_id == current_user.id).delete()
    db.commit()
