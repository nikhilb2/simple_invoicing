"""
Add an index on lower(email) to users.

find_user_by_email falls back to `func.lower(User.email) == lower(?)`
after the exact-match lookup misses, so every unknown or differently
cased address scanned the whole table on public routes (login, register,
resend-verification, forgot-password, Google sign-in). The index is
deliberately not UNIQUE: older accounts may hold values that differ only
in case, and a unique index would block them.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_users_email_lower
        ON users (lower(email))
    """))


def down(conn) -> None:
    conn.execute(text("""
        DROP INDEX IF EXISTS ix_users_email_lower
    """))
