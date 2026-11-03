"""External sign-in identities (Google, and later others) linked to a user.

A user is found by (provider, provider_subject) -- the provider's stable account
id -- never by email alone, because an address can change hands at the provider.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from src.db.base import Base


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_user_identities_provider_subject"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # "google"
    provider = Column(String(32), nullable=False)
    provider_subject = Column(String(255), nullable=False)
    # The address the provider reported at link time; informational only.
    email = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User")
