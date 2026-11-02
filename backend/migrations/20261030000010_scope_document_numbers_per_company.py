"""
Make invoice, credit note and payment numbers unique per company instead of
across the whole database.

Every company's series starts at -001, so in shared hosting a global UNIQUE on
invoice_number makes the second company's INV-2026-001 collide with the first
company's (and the gaps it forces reveal how much other tenants invoice). Each
number column gets UNIQUE (company_id, <number>) plus a plain index for lookups
by number.

The old global uniqueness exists under whichever name created it:
- ix_invoices_invoice_number / ix_credit_notes_credit_note_number, the unique
  indexes Base.metadata.create_all made from `unique=True, index=True`;
- credit_notes_credit_note_number_key, the constraint the credit-notes
  migration made when it created the table itself.
So it is found by shape (a unique index on exactly that one column) rather than
by name. payments.payment_number never had one.

payments may already hold duplicate numbers inside one company, since nothing
stopped it before. Adding the constraint would then fail the whole boot, so it
is skipped with a warning for that database; the series check in
src/services/series.py still keeps new numbers unique per company.

Rows with a NULL company_id escape a (company_id, number) constraint, so on a
database with exactly one company they are first given that company -- the same
backfill 20260424000002 did. With several companies there is no safe owner to
pick, and they are left alone.
"""

from sqlalchemy import text

_NUMBER_COLUMNS = [
    ("invoices", "invoice_number", "uq_invoices_company_invoice_number"),
    ("credit_notes", "credit_note_number", "uq_credit_notes_company_credit_note_number"),
    ("payments", "payment_number", "uq_payments_company_payment_number"),
]


def _single_column_unique_indexes(conn, table: str, column: str) -> list[tuple[str, str | None]]:
    """(index name, owning constraint name or None) for each unique index on just ``column``."""
    rows = conn.execute(text("""
        SELECT i.relname, c.conname
        FROM pg_index x
        JOIN pg_class t ON t.oid = x.indrelid
        JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.indkey[0]
        LEFT JOIN pg_constraint c ON c.conindid = x.indexrelid AND c.contype = 'u'
        WHERE t.relname = :table
          AND t.relnamespace = current_schema()::regnamespace
          AND x.indisunique
          AND NOT x.indisprimary
          AND x.indnatts = 1
          AND a.attname = :column
    """), {"table": table, "column": column}).fetchall()
    return [(row[0], row[1]) for row in rows]


def _constraint_exists(conn, name: str) -> bool:
    return conn.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
        {"name": name},
    ).fetchone() is not None


def _has_duplicates(conn, table: str, column: str) -> bool:
    return conn.execute(text(f"""
        SELECT 1 FROM {table}
        WHERE {column} IS NOT NULL
        GROUP BY company_id, {column}
        HAVING COUNT(*) > 1
        LIMIT 1
    """)).fetchone() is not None


def up(conn) -> None:
    company_ids = conn.execute(text("SELECT id FROM company_profiles LIMIT 2")).fetchall()
    only_company_id = company_ids[0][0] if len(company_ids) == 1 else None

    for table, column, constraint in _NUMBER_COLUMNS:
        if only_company_id is not None:
            conn.execute(
                text(f"UPDATE {table} SET company_id = :company_id WHERE company_id IS NULL"),
                {"company_id": only_company_id},
            )

        for index_name, constraint_name in _single_column_unique_indexes(conn, table, column):
            if constraint_name is not None:
                conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{constraint_name}"'))
            else:
                conn.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))

        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})"))

        if _constraint_exists(conn, constraint):
            continue
        if _has_duplicates(conn, table, column):
            print(
                f"    ⚠️  {table}.{column} has duplicate numbers within a company; "
                f"{constraint} not added. De-duplicate them and add it by hand."
            )
            continue
        conn.execute(text(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} UNIQUE (company_id, {column})"
        ))


def down(conn) -> None:
    for table, column, constraint in _NUMBER_COLUMNS:
        conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"))
    # Only the two columns that were globally unique before.
    conn.execute(text("DROP INDEX IF EXISTS ix_invoices_invoice_number"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_invoices_invoice_number ON invoices (invoice_number)"))
    conn.execute(text("DROP INDEX IF EXISTS ix_credit_notes_credit_note_number"))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_credit_notes_credit_note_number ON credit_notes (credit_note_number)"
    ))
