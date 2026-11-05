"""
Remember each user's answer to the first-invoice walkthrough.

first_invoice_tour_status is NULL until the user answers, then one of:
  completed   they created their first invoice with the walkthrough running
  skipped     they declined it or left part way
  not_needed  their company already had invoices when it would have been offered

NULL for every existing user: the app sets not_needed the next time one of them
opens the dashboard, so nobody with invoices is offered it.

create_all never alters an existing table, so on an existing database the columns
arrive here; on a fresh one IF NOT EXISTS makes this a no-op.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_invoice_tour_status VARCHAR(20)"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_invoice_tour_finished_at TIMESTAMPTZ"))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS first_invoice_tour_finished_at"))
    conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS first_invoice_tour_status"))
