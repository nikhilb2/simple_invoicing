from datetime import datetime
from pydantic import BaseModel, EmailStr


class SmtpConfigCreate(BaseModel):
    name: str
    host: str
    port: int
    username: str
    password: str
    from_email: EmailStr
    from_name: str
    use_tls: bool = True


class SmtpConfigUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    from_email: EmailStr | None = None
    from_name: str | None = None
    use_tls: bool | None = None


class SmtpConfigResponse(BaseModel):
    id: int
    name: str
    host: str
    port: int
    username: str
    from_email: str
    from_name: str
    use_tls: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
