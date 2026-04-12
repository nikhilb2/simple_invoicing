"""
Update credit_notes and credit_note_items to the multi-invoice architecture, and
create the credit_note_invoice_refs join table.

This migration handles upgrading from the old single-invoice schema (if already
applied) as well as a clean install:

Old credit_notes schema:  invoice_id + buyer_id
New credit_notes schema:  ledger_id (renamed from buyer_id), credit_note_type added,
                          invoice_id removed (moved to credit_note_invoice_refs)

Old credit_note_items schema: missing invoice_id and invoice_item_id
New credit_note_items schema: invoice_id + invoice_item_id added (nullable for
                               compat with any existing empty rows)
"""

from sqlalchemy import text


def _column_exists(conn, table: str, column: str) -> bool:
    r = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).fetchone()
    return r is not None


def _table_exists(conn, table: str) -> bool:
    r = conn.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
    ), {"t": table}).fetchone()
    return r is not None


def up(conn) -> None:
    # ── credit_notes: create fresh OR migrate existing ───────────────────────
    if not _table_exists(conn, "credit_notes"):
        conn.execute(text("""
            CREATE TABLE credit_notes (
                id                  SERIAL PRIMARY KEY,
                credit_note_number  VARCHAR NOT NULL UNIQUE,
                ledger_id           INTEGER NOT NULL REFERENCES buyers(id),
                financial_year_id   INTEGER REFERENCES financial_years(id),
                created_by          INTEGER NOT NULL REFERENCES users(id),
                credit_note_type    VARCHAR NOT NULL DEFAULT 'return',
                reason              TEXT,
                status              VARCHAR NOT NULL DEFAULT 'active',
                taxable_amount      NUMERIC(10, 2) NOT NULL DEFAULT 0,
                cgst_amount         NUMERIC(10, 2) NOT NULL DEFAULT 0,
                sgst_amount         NUMERIC(10, 2) NOT NULL DEFAULT 0,
                igst_amount         NUMERIC(10, 2) NOT NULL DEFAULT 0,
                total_amount        NUMERIC(10, 2) NOT NULL DEFAULT 0,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                cancelled_at        TIMESTAMPTZ
            )
        """))
    else:
        # Rename buyer_id → ledger_id if needed
        if _column_exists(conn, "credit_notes", "buyer_id") and not _column_exists(conn, "credit_notes", "ledger_id"):
            conn.execute(text("ALTER TABLE credit_notes RENAME COLUMN buyer_id TO ledger_id"))

        # Drop old invoice_id column (moved to credit_note_invoice_refs)
        if _column_exists(conn, "credit_notes", "invoice_id"):
            conn.execute(text("ALTER TABLE credit_notes DROP COLUMN invoice_id"))

        # Add credit_note_type
        if not _column_exists(conn, "credit_notes", "credit_note_type"):
            conn.execute(text(
                "ALTER TABLE credit_notes ADD COLUMN credit_note_type VARCHAR NOT NULL DEFAULT 'return'"
            ))

    # ── credit_note_invoice_refs: always create if missing ───────────────────
    if not _table_exists(conn, "credit_note_invoice_refs"):
        conn.execute(text("""
            CREATE TABLE credit_note_invoice_refs (
                id              SERIAL PRIMARY KEY,
                credit_note_id  INTEGER NOT NULL REFERENCES credit_notes(id) ON DELETE CASCADE,
                invoice_id      INTEGER NOT NULL REFERENCES invoices(id),
                UNIQUE (credit_note_id, invoice_id)
            )
        """))

    # ── credit_note_items: create fresh OR migrate existing ──────────────────
    if not _table_exists(conn, "credit_note_items"):
        conn.execute(text("""
            CREATE TABLE credit_note_items (
                id                  SERIAL PRIMARY KEY,
                credit_note_id      INTEGER NOT NULL REFERENCES credit_notes(id) ON DELETE CASCADE,
                invoice_id          INTEGER REFERENCES invoices(id),
                invoice_item_id     INTEGER REFERENCES invoice_items(id),
                product_id          INTEGER REFERENCES products(id),
                quantity            INTEGER NOT NULL,
                unit_price          NUMERIC(10, 2) NOT NULL,
                gst_rate            NUMERIC(5, 2) NOT NULL DEFAULT 0,
                taxable_amount      NUMERIC(10, 2) NOT NULL DEFAULT 0,
                tax_amount          NUMERIC(10, 2) NOT NULL DEFAULT 0,
                line_total          NUMERIC(10, 2) NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
    else:
        # Add invoice_id (which invoice this item credits against)
        if not _column_exists(conn, "credit_note_items", "invoice_id"):
            conn.execute(text(
                "ALTER TABLE credit_note_items ADD COLUMN invoice_id INTEGER REFERENCES invoices(id)"
            ))
        # Add invoice_item_id (the original line item being credited)
        if not _column_exists(conn, "credit_note_items", "invoice_item_id"):
            conn.execute(text(
                "ALTER TABLE credit_note_items ADD COLUMN invoice_item_id INTEGER REFERENCES invoice_items(id)"
            ))

    # ── indexes ───────────────────────────────────────────────────────────────
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_credit_notes_ledger_id ON credit_notes(ledger_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_credit_notes_financial_year_id ON credit_notes(financial_year_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cn_invoice_refs_invoice_id ON credit_note_invoice_refs(invoice_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_credit_note_items_invoice_id ON credit_note_items(invoice_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_credit_note_items_invoice_item_id ON credit_note_items(invoice_item_id)"))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS credit_note_items"))
    conn.execute(text("DROP TABLE IF EXISTS credit_note_invoice_refs"))
    conn.execute(text("DROP TABLE IF EXISTS credit_notes"))
