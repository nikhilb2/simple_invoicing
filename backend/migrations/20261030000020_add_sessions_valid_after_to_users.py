"""
Add users.sessions_valid_after: refresh tokens issued before it are refused.

A password reset sets it, so a session someone else started with the old
password stops refreshing. NULL -- every existing user -- revokes nothing, so
nobody is signed out by this migration.

create_all never alters an existing table, so on an existing database the column
arrives here; on a fresh one IF NOT EXISTS makes this a no-op.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS sessions_valid_after TIMESTAMPTZ"))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS sessions_valid_after"))
