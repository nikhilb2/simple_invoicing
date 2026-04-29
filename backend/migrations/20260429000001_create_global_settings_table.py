"""
create_global_settings_table
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS global_settings (
            id INTEGER PRIMARY KEY,
            max_companies INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_global_settings_singleton_id CHECK (id = 1),
            CONSTRAINT ck_global_settings_max_companies_positive CHECK (max_companies > 0)
        )
    """))
    conn.execute(text("""
        INSERT INTO global_settings (id, max_companies)
        VALUES (1, 1)
        ON CONFLICT (id) DO NOTHING
    """))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS global_settings"))
