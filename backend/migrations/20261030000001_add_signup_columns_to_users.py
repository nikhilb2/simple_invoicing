"""
Add the account-lifecycle columns public signup needs to users.

- email_verified_at: NULL until the address is proven. Every user that exists
  now was created by an admin or the seed script, so they are backfilled as
  verified -- nobody already using the app gets locked out by the new check.
- is_active: lets an account be switched off without deleting its history.
- created_at: when the account was made. Existing rows get the migration time,
  which is the best that can be known.
- hashed_password loses NOT NULL: an account created through Google has no
  password until its owner chooses to set one.

create_all runs before migrations but never alters an existing table, so on an
existing database these columns arrive here; on a fresh one create_all already
made them and the IF NOT EXISTS clauses make this a no-op.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"))
    conn.execute(text("ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL"))
    conn.execute(text("UPDATE users SET email_verified_at = NOW() WHERE email_verified_at IS NULL"))


def down(conn) -> None:
    # Restoring NOT NULL on hashed_password would fail for any Google-only account,
    # so it is left nullable.
    conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS created_at"))
    conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS is_active"))
    conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at"))
