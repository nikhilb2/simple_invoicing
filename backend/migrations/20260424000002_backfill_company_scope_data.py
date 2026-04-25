"""Backfill company scope columns with a default company for legacy data."""

from sqlalchemy import text


def _get_or_create_default_company_id(conn) -> int:
    row = conn.execute(text("SELECT id FROM company_profiles ORDER BY id ASC LIMIT 1")).fetchone()
    if row:
        return int(row[0])

    company_id = conn.execute(
        text(
            """
            INSERT INTO company_profiles (
                name,
                address,
                gst,
                phone_number,
                currency_code,
                email,
                website,
                bank_name,
                branch_name,
                account_name,
                account_number,
                ifsc_code
            ) VALUES (
                :name,
                :address,
                :gst,
                :phone_number,
                :currency_code,
                :email,
                :website,
                :bank_name,
                :branch_name,
                :account_name,
                :account_number,
                :ifsc_code
            )
            RETURNING id
            """
        ),
        {
            "name": "Default Company",
            "address": "",
            "gst": "",
            "phone_number": "",
            "currency_code": "USD",
            "email": "",
            "website": "",
            "bank_name": "",
            "branch_name": "",
            "account_name": "",
            "account_number": "",
            "ifsc_code": "",
        },
    ).scalar_one()
    return int(company_id)


def up(conn) -> None:
    default_company_id = _get_or_create_default_company_id(conn)

    conn.execute(
        text(
            "UPDATE users SET active_company_id = :company_id WHERE active_company_id IS NULL"
        ),
        {"company_id": default_company_id},
    )

    tables = [
        "invoices",
        "company_accounts",
        "buyers",
        "products",
        "inventory",
        "payments",
        "credit_notes",
        "credit_note_items",
        "invoice_series",
        "financial_years",
    ]

    for table in tables:
        conn.execute(
            text(f"UPDATE {table} SET company_id = :company_id WHERE company_id IS NULL"),
            {"company_id": default_company_id},
        )


def down(conn) -> None:
    # This rollback intentionally clears only ownership backfill values.
    conn.execute(text("UPDATE users SET active_company_id = NULL"))

    tables = [
        "invoices",
        "company_accounts",
        "buyers",
        "products",
        "inventory",
        "payments",
        "credit_notes",
        "credit_note_items",
        "invoice_series",
        "financial_years",
    ]

    for table in tables:
        conn.execute(text(f"UPDATE {table} SET company_id = NULL"))
