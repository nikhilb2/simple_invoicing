from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from src.db.base import Base


class UserShortcut(Base):
    __tablename__ = "user_shortcuts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action_key = Column(String, nullable=False)
    shortcut_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "action_key", name="uq_user_shortcuts_user_action"),
        Index("ix_user_shortcuts_user_id", "user_id"),
    )
