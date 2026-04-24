from pydantic import BaseModel, EmailStr
from src.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: UserRole = UserRole.staff


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    active_company_id: int | None = None

    class Config:
        from_attributes = True
