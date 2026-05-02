"""
Add Bill of Materials (BOM) support.

Adds:
- is_producable and production_cost fields to products
- bill_of_materials table
- production_transactions table for audit trail
"""

from sqlalchemy import text


def up(conn) -> None:
    # Add BOM fields to products table
    conn.execute(text("""
        ALTER TABLE products
        ADD COLUMN is_producable BOOLEAN NOT NULL DEFAULT FALSE;
    """))
    
    conn.execute(text("""
        ALTER TABLE products
        ADD COLUMN production_cost NUMERIC(12, 2) DEFAULT NULL;
    """))
    
    # Create bill_of_materials table
    conn.execute(text("""
        CREATE TABLE bill_of_materials (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            component_product_id INTEGER NOT NULL,
            quantity_required NUMERIC(12, 3) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES company_profiles(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY (component_product_id) REFERENCES products(id) ON DELETE CASCADE,
            UNIQUE (company_id, product_id, component_product_id)
        );
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_bom_company ON bill_of_materials(company_id);
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_bom_product ON bill_of_materials(product_id);
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_bom_component ON bill_of_materials(component_product_id);
    """))
    
    # Create production_transactions table
    conn.execute(text("""
        CREATE TABLE production_transactions (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity_produced NUMERIC(12, 3) NOT NULL,
            user_id INTEGER NOT NULL,
            notes TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES company_profiles(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_production_company ON production_transactions(company_id);
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_production_product ON production_transactions(product_id);
    """))
    
    conn.execute(text("""
        CREATE INDEX idx_production_created ON production_transactions(created_at);
    """))


def down(conn) -> None:
    conn.execute(text("""
        DROP TABLE IF EXISTS production_transactions CASCADE;
    """))
    
    conn.execute(text("""
        DROP TABLE IF EXISTS bill_of_materials CASCADE;
    """))
    
    conn.execute(text("""
        ALTER TABLE products
        DROP COLUMN IF EXISTS production_cost;
    """))
    
    conn.execute(text("""
        ALTER TABLE products
        DROP COLUMN IF EXISTS is_producable;
    """))
