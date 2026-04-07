from pydantic import BaseModel, Field


class UserShortcutUpdate(BaseModel):
    shortcut_key: str = Field(min_length=1)


class UserShortcutResponse(BaseModel):
    action_key: str
    shortcut_key: str

    class Config:
        from_attributes = True


class UserShortcutsListResponse(BaseModel):
    shortcuts: list[UserShortcutResponse]
