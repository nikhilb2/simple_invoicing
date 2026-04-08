"""
rename_use_tls_to_use_starttls
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE smtp_configs RENAME COLUMN use_tls TO use_starttls"))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE smtp_configs RENAME COLUMN use_starttls TO use_tls"))
