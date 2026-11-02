"""Public share links.

A share link mints an unguessable token that lets an unauthenticated recipient —
typically someone who was sent the URL over WhatsApp — view a single document and
download its PDF. The token is the whole credential, so the row carries the
``company_id`` that every downstream query is then filtered by: that is what stops
a token minted in one tenant from reaching a document in another.

Links are revoked, never deleted. ``revoked_at IS NULL`` means live.
"""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, func, text

from src.db.base import Base


class ShareLink(Base):
    __tablename__ = "share_links"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    # "invoice" | "ledger_statement" | "payment"
    resource_type = Column(String(32), nullable=False)
    # Deliberately not a foreign key: the column is polymorphic across three tables.
    resource_id = Column(Integer, nullable=False)
    # Only ledger statements use these — a statement is a document *and* a period.
    from_date = Column(Date, nullable=True)
    to_date = Column(Date, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    # server_default so a raw-SQL INSERT (data migrations, restores) still gets a 0
    # rather than a NULL that would blow up the increment on the next view.
    view_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_viewed_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())

    # NOTE: the partial unique index that keeps at most one LIVE link per resource
    # (ux_share_links_live_resource) lives in the migration only. It is a Postgres
    # partial index and the test suite builds its schema with create_all() on SQLite.
