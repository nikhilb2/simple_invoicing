"""
Make buyer (ledger) GST optional
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("UPDATE buyers SET gst = NULL WHERE btrim(gst) = ''"))
    conn.execute(text("ALTER TABLE buyers ALTER COLUMN gst DROP NOT NULL"))


def down(conn) -> None:
    conn.execute(text("UPDATE buyers SET gst = '' WHERE gst IS NULL"))
    conn.execute(text("ALTER TABLE buyers ALTER COLUMN gst SET NOT NULL"))
