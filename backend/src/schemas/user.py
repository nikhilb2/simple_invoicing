from pydantic import BaseModel, EmailStr
from src.models.user import UserRole
from src.schemas.auth import NewPassword


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: NewPassword
    role: UserRole = UserRole.staff


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    active_company_id: int | None = None
    # Read from the User properties of the same names. has_password is False for
    # a Google-only account, which is how the app knows to offer "set a password"
    # rather than "change password".
    has_password: bool = False
    email_verified: bool = False
    # `role` is the account's global role. These two are what the UI should gate
    # on: the role in the active company (a shared-hosting signup is global
    # staff but admin of the company they created), and whether the user runs
    # the deployment itself. Filled in by GET /auth/me, which has the session.
    company_role: UserRole | None = None
    can_manage_platform: bool = False

    class Config:
        from_attributes = True
