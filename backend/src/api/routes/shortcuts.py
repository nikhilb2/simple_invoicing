from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.core.shortcuts import SHORTCUTS, ShortcutAction, load_shortcuts

router = APIRouter()


class ShortcutExecuteRequest(BaseModel):
    key: str = Field(..., description="Shortcut action key to execute")


class ShortcutExecuteResponse(BaseModel):
    key: str
    status: str
    path: str | None = None
    message: str




@router.get("")
@router.get("/", response_model=list[ShortcutAction])
def list_shortcuts():
    return load_shortcuts()


@router.post("/execute", response_model=ShortcutExecuteResponse)
def execute_shortcut(payload: ShortcutExecuteRequest):
    shortcuts = load_shortcuts()
    shortcut = next((item for item in shortcuts if item.key == payload.key), None)
    if not shortcut:
        raise HTTPException(status_code=404, detail=f"Shortcut '{payload.key}' not found")

    if shortcut.kind == "navigate":
        return ShortcutExecuteResponse(
            key=shortcut.key,
            status="ok",
            path=shortcut.path,
            message=f"Navigate to {shortcut.path}",
        )

    raise HTTPException(status_code=400, detail=f"Unsupported shortcut kind '{shortcut.kind}'")
