"""
Create quotations and quotation_items: offers, on their own tables so that no report,
stock movement or return can ever read one as an invoice.

IF NOT EXISTS throughout: boot runs create_all before migrations, so these tables
usually exist by the time this runs.

Shared hosting: boot applies the row-level security policies to both tables
(src/db/rls.py). The app role's grants come from ALTER DEFAULT PRIVILEGES, and the
boot check refuses to start if they are missing.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS quotations (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id),
            document_type VARCHAR(16) NOT NULL,
            quotation_number VARCHAR NOT NULL,
            status VARCHAR(16) NOT NULL,
            quotation_date DATE NOT NULL,
            valid_until DATE,
            financial_year_id INTEGER REFERENCES financial_years(id),
            ledger_id INTEGER NOT NULL REFERENCES buyers(id),
            ledger_name VARCHAR,
            ledger_address VARCHAR,
            ledger_gst VARCHAR,
            ledger_phone VARCHAR,
            company_name VARCHAR,
            company_address VARCHAR,
            company_gst VARCHAR,
            company_phone VARCHAR,
            company_email VARCHAR,
            company_website VARCHAR,
            company_currency_code VARCHAR,
            company_bank_name VARCHAR,
            company_branch_name VARCHAR,
            company_account_name VARCHAR,
            company_account_number VARCHAR,
            company_ifsc_code VARCHAR,
            company_logo_data TEXT,
            company_logo_mime_type VARCHAR(50),
            company_additional_info TEXT,
            company_terms_text TEXT,
            shipping_address TEXT,
            shipping_address_label VARCHAR(255),
            shipping_address_id INTEGER REFERENCES ledger_addresses(id) ON DELETE SET NULL,
            reference_notes VARCHAR,
            tax_inclusive BOOLEAN NOT NULL,
            apply_round_off BOOLEAN NOT NULL,
            round_off_amount NUMERIC(5, 2) NOT NULL,
            discount_type VARCHAR(20),
            discount_value NUMERIC(10, 2),
            taxable_amount NUMERIC(10, 2) NOT NULL,
            total_tax_amount NUMERIC(10, 2) NOT NULL,
            cgst_amount NUMERIC(10, 2) NOT NULL,
            sgst_amount NUMERIC(10, 2) NOT NULL,
            igst_amount NUMERIC(10, 2) NOT NULL,
            total_amount NUMERIC(10, 2) NOT NULL,
            status_note VARCHAR,
            accepted_at TIMESTAMP,
            declined_at TIMESTAMP,
            converted_at TIMESTAMP,
            cancelled_at TIMESTAMP,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            CONSTRAINT uq_quotations_company_number UNIQUE (company_id, quotation_number)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotations_id ON quotations (id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotations_ledger_id ON quotations (ledger_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotations_company_status ON quotations (company_id, status)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotations_company_date ON quotations (company_id, quotation_date)"))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS quotation_items (
            id SERIAL PRIMARY KEY,
            quotation_id INTEGER NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            hsn_sac VARCHAR,
            quantity NUMERIC(12, 3) NOT NULL,
            unit_price NUMERIC(10, 2) NOT NULL,
            gst_rate NUMERIC(5, 2) NOT NULL,
            taxable_amount NUMERIC(10, 2) NOT NULL,
            tax_amount NUMERIC(10, 2) NOT NULL,
            cgst_amount NUMERIC(10, 2) NOT NULL,
            sgst_amount NUMERIC(10, 2) NOT NULL,
            igst_amount NUMERIC(10, 2) NOT NULL,
            line_total NUMERIC(10, 2) NOT NULL,
            description TEXT,
            discount_type VARCHAR(20),
            discount_value NUMERIC(10, 2)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotation_items_id ON quotation_items (id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotation_items_quotation_id ON quotation_items (quotation_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotation_items_product_id ON quotation_items (product_id)"))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS quotation_items"))
    conn.execute(text("DROP TABLE IF EXISTS quotations"))
