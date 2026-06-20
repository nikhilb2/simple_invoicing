from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, v: datetime) -> datetime:
        from datetime import timezone, timedelta
        now = datetime.now(timezone.utc)
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= now:
            raise ValueError("expires_at must be in the future")
        max_expiry = now + timedelta(days=365)
        if v > max_expiry:
            raise ValueError("expires_at cannot be more than 1 year from now")
        return v


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    expires_at: datetime
    is_active: bool
    created_at: datetime
    created_by_user_id: int

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyResponse):
    """Returned only on creation — includes the full plaintext key (shown once)."""
    raw_key: str
