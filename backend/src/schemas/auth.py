from pydantic import BaseModel, EmailStr, Field


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
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordResponse(BaseModel):
    detail: str


class DetailResponse(BaseModel):
    detail: str


class RegisterRequest(BaseModel):
    email: EmailStr
    # The upper bound is for bcrypt, which silently ignores everything past 72
    # bytes, and for the cost of hashing whatever an anonymous caller sends.
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)


class EmailRequest(BaseModel):
    email: EmailStr


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    new_password: str = Field(min_length=8, max_length=128)


class OAuthExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class AuthProviderOut(BaseModel):
    id: str
    name: str


class AuthConfigOut(BaseModel):
    password_signup_enabled: bool
    password_reset_enabled: bool
    providers: list[AuthProviderOut]
