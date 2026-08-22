"""
create_marketplace_tables

CREATE TABLE IF NOT EXISTS throughout: app_main.py runs Base.metadata.create_all()
before the migration runner, so on a fresh database these tables already exist by
the time this runs.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS marketplace_connections (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL UNIQUE REFERENCES company_profiles(id) ON DELETE CASCADE,
            base_url VARCHAR(500) NOT NULL,
            remote_seller_id VARCHAR(100),
            gstin VARCHAR(20),
            display_name VARCHAR(255),
            credential_encrypted TEXT,
            credential_prefix VARCHAR(32),
            instance_uuid VARCHAR(64),
            status VARCHAR(32) NOT NULL DEFAULT 'unregistered',
            sync_cursor BIGINT NOT NULL DEFAULT 0,
            sync_lock_until TIMESTAMP,
            last_sync_at TIMESTAMP,
            last_sync_error TEXT,
            auto_accept BOOLEAN NOT NULL DEFAULT TRUE,
            auto_accept_max_amount NUMERIC(12, 2),
            auto_post BOOLEAN NOT NULL DEFAULT FALSE,
            created_by_user_id INTEGER REFERENCES users(id),
            registered_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS marketplace_listings (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            remote_listing_id VARCHAR(100),
            title VARCHAR(255) NOT NULL,
            description TEXT,
            asking_price NUMERIC(12, 2) NOT NULL DEFAULT 0,
            currency_code VARCHAR(8) NOT NULL DEFAULT 'INR',
            gst_rate NUMERIC(5, 2) NOT NULL DEFAULT 0,
            hsn_sac VARCHAR(20),
            unit VARCHAR(50) NOT NULL DEFAULT 'Pieces',
            allow_decimal BOOLEAN NOT NULL DEFAULT FALSE,
            min_order_quantity NUMERIC(12, 3),
            max_order_quantity NUMERIC(12, 3),
            available_quantity_published NUMERIC(12, 3),
            status VARCHAR(32) NOT NULL DEFAULT 'draft',
            listing_type VARCHAR(32) NOT NULL DEFAULT 'buy_now',
            last_published_at TIMESTAMP,
            last_error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT ux_marketplace_listings_company_product UNIQUE (company_id, product_id),
            CONSTRAINT ux_marketplace_listings_company_remote UNIQUE (company_id, remote_listing_id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_marketplace_listings_company_id "
        "ON marketplace_listings (company_id)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS marketplace_orders (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            side VARCHAR(8) NOT NULL,
            remote_order_id VARCHAR(100) NOT NULL,
            order_type VARCHAR(32) NOT NULL DEFAULT 'buy_now',
            state VARCHAR(32) NOT NULL DEFAULT 'pending',
            remote_listing_id VARCHAR(100),
            counterparty_remote_id VARCHAR(100),
            counterparty_name VARCHAR(255),
            counterparty_gstin VARCHAR(20),
            counterparty_address TEXT,
            counterparty_phone VARCHAR(50),
            counterparty_email VARCHAR(255),
            currency_code VARCHAR(8) NOT NULL DEFAULT 'INR',
            remote_total_amount NUMERIC(14, 2),
            order_placed_at TIMESTAMP,
            expires_at TIMESTAMP,
            accepted_at TIMESTAMP,
            closed_at TIMESTAMP,
            reject_reason VARCHAR(64),
            reject_note TEXT,
            seller_invoice_number VARCHAR(100),
            seller_invoice_date TIMESTAMP,
            posting_state VARCHAR(32) NOT NULL DEFAULT 'not_required',
            posting_lock_until TIMESTAMP,
            posted_invoice_id INTEGER REFERENCES invoices(id),
            posted_at TIMESTAMP,
            posting_error TEXT,
            posting_attempts INTEGER NOT NULL DEFAULT 0,
            posting_warnings TEXT,
            total_mismatch BOOLEAN NOT NULL DEFAULT FALSE,
            remote_posting_reported BOOLEAN NOT NULL DEFAULT FALSE,
            last_event_seq BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT ux_marketplace_orders_company_remote UNIQUE (company_id, remote_order_id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_marketplace_orders_company_id "
        "ON marketplace_orders (company_id)"
    ))
    # The posting reconciler's only query shape.
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_marketplace_orders_posting_state "
        "ON marketplace_orders (company_id, posting_state, id)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS marketplace_order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES marketplace_orders(id) ON DELETE CASCADE,
            line_no INTEGER NOT NULL,
            remote_listing_id VARCHAR(100),
            title VARCHAR(255),
            product_id INTEGER REFERENCES products(id),
            quantity NUMERIC(12, 3) NOT NULL DEFAULT 0,
            unit VARCHAR(50),
            unit_price NUMERIC(12, 2) NOT NULL DEFAULT 0,
            gst_rate NUMERIC(5, 2) NOT NULL DEFAULT 0,
            hsn_sac VARCHAR(20),
            CONSTRAINT ux_marketplace_order_items_order_line UNIQUE (order_id, line_no)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_marketplace_order_items_order_id "
        "ON marketplace_order_items (order_id)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS marketplace_processed_events (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            event_id VARCHAR(100) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            seq BIGINT NOT NULL DEFAULT 0,
            remote_order_id VARCHAR(100),
            result VARCHAR(16) NOT NULL DEFAULT 'applied',
            error TEXT,
            payload TEXT,
            received_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT ux_marketplace_events_company_event UNIQUE (company_id, event_id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_marketplace_events_company_seq "
        "ON marketplace_processed_events (company_id, seq)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS marketplace_product_links (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            remote_listing_id VARCHAR(100) NOT NULL,
            product_id INTEGER NOT NULL REFERENCES products(id),
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT ux_marketplace_product_links_company_listing
                UNIQUE (company_id, remote_listing_id)
        )
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS marketplace_ledger_links (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            remote_seller_id VARCHAR(100) NOT NULL,
            ledger_id INTEGER NOT NULL REFERENCES buyers(id),
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT ux_marketplace_ledger_links_company_seller
                UNIQUE (company_id, remote_seller_id)
        )
    """))


def down(conn) -> None:
    # Children first — marketplace_orders is referenced by marketplace_order_items.
    conn.execute(text("DROP TABLE IF EXISTS marketplace_ledger_links"))
    conn.execute(text("DROP TABLE IF EXISTS marketplace_product_links"))
    conn.execute(text("DROP TABLE IF EXISTS marketplace_processed_events"))
    conn.execute(text("DROP TABLE IF EXISTS marketplace_order_items"))
    conn.execute(text("DROP TABLE IF EXISTS marketplace_orders"))
    conn.execute(text("DROP TABLE IF EXISTS marketplace_listings"))
    conn.execute(text("DROP TABLE IF EXISTS marketplace_connections"))
