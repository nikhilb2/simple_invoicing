"""Scope financial year label uniqueness per company."""

from sqlalchemy import text


def up(conn) -> None:
    # Remove legacy global uniqueness on label.
    conn.execute(text("""
        ALTER TABLE financial_years
        DROP CONSTRAINT IF EXISTS uq_financial_years_label
    """))

    # Ensure scoped uniqueness for company + label.
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_years_company_id_label
        ON financial_years(company_id, label)
    """))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ux_financial_years_company_id_label"))

    conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_financial_years_label'
            ) THEN
                ALTER TABLE financial_years
                    ADD CONSTRAINT uq_financial_years_label UNIQUE (label);
            END IF;
        END
        $$
    """))
