"""
Create email_logs table to track all outbound emails.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS email_logs (
            id SERIAL PRIMARY KEY,
            company_id INTEGER REFERENCES company_profiles(id) ON DELETE SET NULL,
            to_email TEXT NOT NULL,
            cc TEXT DEFAULT NULL,
            subject TEXT NOT NULL,
            email_type TEXT NOT NULL DEFAULT 'other',
            reference_id INTEGER DEFAULT NULL,
            status TEXT NOT NULL DEFAULT 'sent',
            error_message TEXT DEFAULT NULL,
            sent_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_email_logs_company_id ON email_logs(company_id);
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_email_logs_sent_at ON email_logs(sent_at DESC);
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_email_logs_status ON email_logs(status);
    """))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS email_logs;"))
