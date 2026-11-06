"""Which companies a user belongs to, and with what role.

Only consulted in shared hosting (see src/services/company_access.py). A
single-tenant deployment lets every user reach every company with their global
role, exactly as before memberships existed; its rows are backfilled anyway so
that switching a database over to shared hosting changes nobody's access.
"""

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import relationship

from src.db.base import Base
from src.models.user import UserRole


class CompanyMembership(Base):
    __tablename__ = "company_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_company_memberships_user_company"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    # Same Postgres enum type as users.role.
    role = Column(Enum(UserRole), nullable=False, default=UserRole.staff)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # One-way on purpose: a backref on User/CompanyProfile would make the ORM try
    # to NULL user_id/company_id on delete instead of leaving it to ON DELETE CASCADE.
    user = relationship("User")
    company = relationship("CompanyProfile")
