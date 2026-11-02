"""Single-use codes that hand a social sign-in back to the web app.

The OAuth callback must not put JWTs in a redirect URL (they would land in
browser history and proxy logs), so it redirects with one of these instead and
the app swaps it for tokens. Only the sha256 of the code is stored, and it lives
for seconds.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from src.db.base import Base


class OAuthLoginCode(Base):
    __tablename__ = "oauth_login_codes"

    id = Column(Integer, primary_key=True, index=True)
    # sha256 hex digest of the code handed to the browser.
    code_hash = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
