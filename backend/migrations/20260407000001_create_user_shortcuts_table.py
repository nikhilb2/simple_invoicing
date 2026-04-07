"""
create_user_shortcuts_table
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS user_shortcuts (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action_key VARCHAR NOT NULL,
            shortcut_key VARCHAR NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_shortcuts_user_action UNIQUE (user_id, action_key)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_shortcuts_user_id ON user_shortcuts (user_id)"))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS user_shortcuts"))
