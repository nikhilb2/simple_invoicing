"""
add_oauth_server

Tables for the built-in OAuth 2.1 authorization server: dynamic client
registrations, parked /authorize requests, one-shot authorization codes and
issued access/refresh tokens.

IF NOT EXISTS throughout: app_main.py runs Base.metadata.create_all() before the
migration runner, so on a fresh database every table and index below already
exists by the time this executes. This file is what brings an *existing*
database up to the same shape, and it is also where Postgres-only DDL lives —
the models themselves have to stay SQLite-compatible for the test suite.
"""

from sqlalchemy import text


def up(conn) -> None:
    """Apply migration."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oauth_clients (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(64) NOT NULL UNIQUE,
            client_secret_hash VARCHAR(64),
            client_name VARCHAR(255) NOT NULL,
            client_uri VARCHAR(2048),
            logo_uri VARCHAR(2048),
            redirect_uris TEXT NOT NULL,
            grant_types TEXT NOT NULL DEFAULT 'authorization_code refresh_token',
            response_types TEXT NOT NULL DEFAULT 'code',
            scope TEXT NOT NULL DEFAULT '',
            token_endpoint_auth_method VARCHAR(32) NOT NULL DEFAULT 'none',
            software_id VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_oauth_clients_client_id "
        "ON oauth_clients (client_id)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oauth_auth_requests (
            id SERIAL PRIMARY KEY,
            request_id VARCHAR(64) NOT NULL UNIQUE,
            client_id VARCHAR(64) NOT NULL,
            redirect_uri TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT '',
            state TEXT,
            code_challenge VARCHAR(255) NOT NULL,
            code_challenge_method VARCHAR(16) NOT NULL DEFAULT 'S256',
            resource TEXT,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_oauth_auth_requests_request_id "
        "ON oauth_auth_requests (request_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_oauth_auth_requests_client_id "
        "ON oauth_auth_requests (client_id)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
            id SERIAL PRIMARY KEY,
            code_hash VARCHAR(64) NOT NULL UNIQUE,
            client_id VARCHAR(64) NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
            scope TEXT NOT NULL DEFAULT '',
            redirect_uri TEXT NOT NULL,
            code_challenge VARCHAR(255) NOT NULL,
            code_challenge_method VARCHAR(16) NOT NULL DEFAULT 'S256',
            resource TEXT,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_oauth_authorization_codes_code_hash "
        "ON oauth_authorization_codes (code_hash)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_oauth_authorization_codes_user_id "
        "ON oauth_authorization_codes (user_id)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id SERIAL PRIMARY KEY,
            token_type VARCHAR(16) NOT NULL,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            client_id VARCHAR(64) NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
            scope TEXT NOT NULL DEFAULT '',
            resource TEXT,
            auth_code_id INTEGER REFERENCES oauth_authorization_codes(id) ON DELETE SET NULL,
            parent_id INTEGER REFERENCES oauth_tokens(id) ON DELETE SET NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_oauth_tokens_token_hash "
        "ON oauth_tokens (token_hash)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_oauth_tokens_user_id ON oauth_tokens (user_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_oauth_tokens_client_id ON oauth_tokens (client_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_oauth_tokens_auth_code_id ON oauth_tokens (auth_code_id)"
    ))

    # Postgres-only. The Settings "connected apps" list and every chain revocation
    # read exactly this shape; a partial index keeps expired/revoked rows out of it
    # and cannot be expressed on the model without breaking the SQLite test schema.
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_oauth_tokens_live_grants "
        "ON oauth_tokens (user_id, client_id) WHERE revoked_at IS NULL"
    ))


def down(conn) -> None:
    """Revert migration."""
    conn.execute(text("DROP TABLE IF EXISTS oauth_tokens"))
    conn.execute(text("DROP TABLE IF EXISTS oauth_authorization_codes"))
    conn.execute(text("DROP TABLE IF EXISTS oauth_auth_requests"))
    conn.execute(text("DROP TABLE IF EXISTS oauth_clients"))
