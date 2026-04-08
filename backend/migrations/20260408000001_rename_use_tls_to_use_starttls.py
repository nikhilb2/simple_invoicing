"""
rename_use_tls_to_use_starttls
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'smtp_configs' AND column_name = 'use_tls'
            ) THEN
                ALTER TABLE smtp_configs RENAME COLUMN use_tls TO use_starttls;
            END IF;
        END $$;
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE smtp_configs RENAME COLUMN use_starttls TO use_tls"))
