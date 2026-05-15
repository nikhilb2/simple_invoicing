from sqlalchemy import Column, Integer, Text, DateTime
from sqlalchemy.sql import func
from src.db.base import Base


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, nullable=True)
    to_email = Column(Text, nullable=False)
    cc = Column(Text, nullable=True)
    subject = Column(Text, nullable=False)
    email_type = Column(Text, nullable=False, default="other")
    reference_id = Column(Integer, nullable=True)
    status = Column(Text, nullable=False, default="sent")
    error_message = Column(Text, nullable=True)
    sent_by_user_id = Column(Integer, nullable=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
