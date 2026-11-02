"""
Add api_keys table for company-scoped, encrypted API key management.
Keys are used to authenticate the MCP server without short-lived JWTs.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            created_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            key_prefix VARCHAR(12) NOT NULL,
            key_encrypted TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_company_id ON api_keys(company_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_key_prefix ON api_keys(key_prefix)"))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS api_keys"))
