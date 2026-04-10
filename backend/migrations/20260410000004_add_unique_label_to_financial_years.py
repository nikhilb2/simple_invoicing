"""
Add UNIQUE constraint on financial_years.label to prevent duplicate FY entries.
"""

from sqlalchemy import text


def up(conn) -> None:
    # Remove duplicate labels, keeping the row with the lowest id for each label.
    # Must delete child rows in invoice_series first due to FK constraint.
    conn.execute(text("""
        DELETE FROM invoice_series
        WHERE financial_year_id IN (
            SELECT id FROM financial_years
            WHERE id NOT IN (
                SELECT MIN(id) FROM financial_years GROUP BY label
            )
        )
    """))

    conn.execute(text("""
        DELETE FROM financial_years
        WHERE id NOT IN (
            SELECT MIN(id) FROM financial_years GROUP BY label
        )
    """))

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


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE financial_years
            DROP CONSTRAINT IF EXISTS uq_financial_years_label
    """))
