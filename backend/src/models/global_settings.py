from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Integer

from src.db.base import Base


class GlobalSettings(Base):
    __tablename__ = "global_settings"

    id = Column(Integer, primary_key=True, default=1)
    max_companies = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_global_settings_singleton_id"),
        CheckConstraint("max_companies > 0", name="ck_global_settings_max_companies_positive"),
    )
