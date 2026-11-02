"""
Create the tables behind social sign-in.

- user_identities links a provider account (Google's `sub`) to a user. Unique
  on (provider, provider_subject) so one Google account maps to one user.
- oauth_login_codes holds the single-use codes the OAuth callback redirects
  back to the web app with, so tokens never travel in a URL. Only a sha256 of
  each code is stored.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS user_identities (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(32) NOT NULL,
            provider_subject VARCHAR(255) NOT NULL,
            email VARCHAR,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_identities_provider_subject UNIQUE (provider, provider_subject)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_identities_id ON user_identities(id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_identities_user_id ON user_identities(user_id)"))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oauth_login_codes (
            id SERIAL PRIMARY KEY,
            code_hash VARCHAR(64) NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_oauth_login_codes_id ON oauth_login_codes(id)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_oauth_login_codes_code_hash ON oauth_login_codes(code_hash)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_oauth_login_codes_user_id ON oauth_login_codes(user_id)"))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS oauth_login_codes"))
    conn.execute(text("DROP TABLE IF EXISTS user_identities"))
