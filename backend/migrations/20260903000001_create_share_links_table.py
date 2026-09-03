"""
Create share_links: public, unauthenticated links to a single invoice, ledger
statement or receipt.

The partial unique index is the interesting part. "Share this invoice" must be
idempotent — pressing it twice has to hand back the same WhatsApp URL, not mint a
second live token for the same document. The uniqueness only applies while the row
is live, so a revoked link never blocks a fresh one for the same resource.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS share_links (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id),
            token VARCHAR(64) NOT NULL UNIQUE,
            resource_type VARCHAR(32) NOT NULL,
            resource_id INTEGER NOT NULL,
            from_date DATE,
            to_date DATE,
            revoked_at TIMESTAMP,
            view_count INTEGER NOT NULL DEFAULT 0,
            last_viewed_at TIMESTAMP,
            created_by_user_id INTEGER REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_share_links_company_id ON share_links(company_id)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_share_links_token ON share_links(token)"))
    # CAVEAT: Postgres treats NULLs as distinct in a unique index, so this index does
    # NOT constrain invoices/receipts (whose from_date/to_date are both NULL) — only
    # ledger statements, which always carry a period. The authoritative idempotency
    # guarantee is the "return the existing live link" lookup in
    # src/api/routes/share.py; this index is a backstop for the statement case.
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_share_links_live_resource
        ON share_links (company_id, resource_type, resource_id, from_date, to_date)
        WHERE revoked_at IS NULL
    """))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ux_share_links_live_resource"))
    conn.execute(text("DROP INDEX IF EXISTS ix_share_links_token"))
    conn.execute(text("DROP INDEX IF EXISTS ix_share_links_company_id"))
    conn.execute(text("DROP TABLE IF EXISTS share_links"))
