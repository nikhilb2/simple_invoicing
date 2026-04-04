from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class SmtpConfigCreate(BaseModel):
    name: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    from_email: EmailStr
    from_name: str = Field(min_length=1)
    use_tls: bool = True


class SmtpConfigUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    from_email: EmailStr | None = None
    from_name: str | None = None
    use_tls: bool | None = None


class SmtpConfigTest(BaseModel):
    id: int
    to: EmailStr


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
    is_active: bool

    class Config:
        from_attributes = True
