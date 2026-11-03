from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

BCRYPT_MAX_BYTES = 72


def _check_password_bytes(value: str) -> str:
    # bcrypt ignores everything past 72 bytes, and a character can take up to 4.
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes long")
    return value


NewPassword = Annotated[str, Field(min_length=8, max_length=128), AfterValidator(_check_password_bytes)]


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    # Optional only for an account with no password yet (signed up with Google):
    # that is how such a user sets their first one. The route still demands it
    # whenever a password exists.
    current_password: str | None = None
    new_password: NewPassword


class ChangePasswordResponse(BaseModel):
    detail: str
    # Changing the password ends every session, so the browser that did it gets a new
    # pair to stay signed in. Absent for a caller that is not a signed-in browser.
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None


class DetailResponse(BaseModel):
    detail: str


class RegisterRequest(BaseModel):
    # No password here: anyone can type anyone's address, so a password set now could
    # be a stranger's. It is chosen on the page the verification link opens.
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)


class EmailRequest(BaseModel):
    email: EmailStr


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    new_password: NewPassword


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    new_password: NewPassword


class OAuthExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class AuthProviderOut(BaseModel):
    id: str
    name: str


class AuthConfigOut(BaseModel):
    password_signup_enabled: bool
    password_reset_enabled: bool
    providers: list[AuthProviderOut]
