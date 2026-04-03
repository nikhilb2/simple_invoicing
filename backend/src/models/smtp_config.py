from src.db.base import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime
from src.core.security import encrypt_value, decrypt_value

class SMTPConfig(Base):
    __tablename__ = "smtp_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String(255), nullable=False)
    _password = Column("password", Text, nullable=False)  # stores ciphertext
    from_email = Column(String(255), nullable=False)
    from_name = Column(String(255), nullable=True)
    use_tls = Column(Boolean, default=True)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    

    @property
    def password(self) -> str:
        return decrypt_value(self._password)

    @password.setter
    def password(self, value: str):
        self._password = encrypt_value(value)

