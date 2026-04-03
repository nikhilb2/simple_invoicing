"""
create_smtp_configs_table
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS smtp_configs (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            host VARCHAR(255) NOT NULL,
            port INTEGER NOT NULL,
            username VARCHAR(255) NOT NULL,
            password TEXT NOT NULL,
            from_email VARCHAR(255) NOT NULL,
            from_name VARCHAR(255),
            use_tls BOOLEAN NOT NULL DEFAULT TRUE,
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS smtp_configs"))
