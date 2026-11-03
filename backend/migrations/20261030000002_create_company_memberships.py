"""
Create company_memberships and give every existing user a membership in every
existing company, with the role they already hold.

Until now every user could reach every company with one global role. Shared
hosting decides access by membership instead, so backfilling the full
user x company grid with the current role means no existing user gains or
loses anything, whichever mode the deployment runs in.

The role column reuses the userrole enum type that users.role already created.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS company_memberships (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            role userrole NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_company_memberships_user_company UNIQUE (user_id, company_id)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_company_memberships_id ON company_memberships(id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_company_memberships_user_id ON company_memberships(user_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_company_memberships_company_id ON company_memberships(company_id)"))
    conn.execute(text("""
        INSERT INTO company_memberships (user_id, company_id, role)
        SELECT u.id, c.id, u.role
        FROM users u
        CROSS JOIN company_profiles c
        ON CONFLICT (user_id, company_id) DO NOTHING
    """))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS company_memberships"))
