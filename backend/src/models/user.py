import enum
from sqlalchemy import Column, Integer, String, Enum, ForeignKey
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
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.staff, nullable=False)
    active_company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
