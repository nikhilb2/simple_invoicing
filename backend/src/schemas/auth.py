from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints

BCRYPT_MAX_BYTES = 72

# The passwords people reach for first, so the first ones anyone guesses. Lowercase,
# because the check ignores case. Only checked when a password is chosen, never at
# sign-in: an account that already has one of these can still get in and change it.
# Mirrored in frontend/src/utils/verifyEmailForm.ts.
COMMON_PASSWORDS = frozenset({
    "00000000", "11111111", "11223344", "12341234", "12344321", "12345678",
    "123456789", "1234567890", "87654321", "1q2w3e4r", "1qaz2wsx",
    "abc12345", "abc@1234", "abc@12345", "abcd1234", "abcd@1234", "abcdefgh",
    "admin123", "admin1234", "admin@123", "administrator", "asdfasdf", "asdfghjk",
    "baseball", "changeme", "football", "iloveyou", "india123", "india@123",
    "letmein1", "letmein123", "p@ssw0rd", "p@ssword", "passw0rd", "password",
    "password1", "password12", "password123", "password1234", "password@1",
    "password@123", "princess", "qwerty12", "qwerty123", "qwerty@123", "qwertyui",
    "qwertyuiop", "sunshine", "superman", "test1234", "test@123", "trustno1",
    "welcome1", "welcome123", "welcome@123",
})


def _check_password_bytes(value: str) -> str:
    # bcrypt ignores everything past 72 bytes, and a character can take up to 4.
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes long")
    return value


def _check_password_not_common(value: str) -> str:
    if value.lower() in COMMON_PASSWORDS:
        raise ValueError("This password is too common and easy to guess. Choose a less obvious one, such as three unrelated words.")
    return value


NewPassword = Annotated[
    str,
    Field(min_length=8, max_length=128),
    AfterValidator(_check_password_bytes),
    AfterValidator(_check_password_not_common),
]


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


class VerifyEmailDetailsRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


class VerifyEmailDetailsOut(BaseModel):
    # What registration stored, for the owner to check and correct. Empty when
    # registration gave no name of its own.
    full_name: str


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    new_password: NewPassword


class VerifyEmailResponse(BaseModel):
    detail: str
    # Set only for the browser that asked for the link; see _asked_for_link_here.
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None


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
