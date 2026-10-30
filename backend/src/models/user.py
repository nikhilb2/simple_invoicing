import enum
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Enum, ForeignKey, func, text
from src.db.base import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    staff = "staff"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    # Nullable for accounts that only ever signed in with Google.
    hashed_password = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.staff, nullable=False)
    active_company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    # NULL until the address is proven. Only shared hosting refuses sign-in on it;
    # every user that existed before signup was added is backfilled as verified.
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    @property
    def has_password(self) -> bool:
        return bool(self.hashed_password)

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None
