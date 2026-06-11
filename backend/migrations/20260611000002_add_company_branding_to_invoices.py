from sqlalchemy import text

def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS company_terms JSONB"))
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS company_additional_info TEXT"))

def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS company_terms"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS company_additional_info"))
