"""Add PAN/TAN identity fields and the effective-dated TDS/TCS section catalogue."""

from sqlalchemy import text


# threshold_single is a per-bill/transaction limit; threshold_aggregate is a tax-year limit.
_SECTIONS = [
    ("tds", 1961, "194C", "194C", "Payment to contractor", 1, 2, 20, 30000, 100000, "per bill / tax year", "taxable", "2025-04-01", "2026-03-31"),
    ("tds", 1961, "194H", "194H", "Commission or brokerage", 2, 2, 20, None, 20000, "per tax year", "taxable", "2025-04-01", "2026-03-31"),
    ("tds", 1961, "194-I(a)", "194-I", "Rent of plant, machinery or equipment", 2, 2, 20, 50000, None, "per month", "taxable", "2025-04-01", "2026-03-31"),
    ("tds", 1961, "194-I(b)", "194-I", "Rent of land, building or furniture", 10, 10, 20, 50000, None, "per month", "taxable", "2025-04-01", "2026-03-31"),
    ("tds", 1961, "194J", "194J", "Fees for technical services, call centre or film royalty", 2, 2, 20, None, 50000, "per tax year", "taxable", "2025-04-01", "2026-03-31"),
    ("tds", 1961, "194J", "194J", "Professional fees and other specified sums", 10, 10, 20, None, 50000, "per tax year", "taxable", "2025-04-01", "2026-03-31"),
    ("tds", 1961, "194Q", "194Q", "Purchase of goods above the annual threshold", 0.1, 0.1, 5, None, 5000000, "excess over threshold", "taxable", "2025-04-01", "2026-03-31"),
    ("tds", 1961, "194T", "194T", "Payments to partners of a firm", 10, 10, 20, None, 20000, "per tax year", "taxable", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1) Sl. No. (i)", "206C(1)", "Sale of alcoholic liquor for human consumption", 1, 1, 5, None, None, None, "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1) Sl. No. (ii)", "206C(1)", "Sale of tendu leaves", 5, 5, 10, None, None, None, "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1) Sl. No. (iii)", "206C(1)", "Sale of timber or other forest produce under a forest lease", 2, 2, 5, None, None, None, "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1) Sl. No. (iv)", "206C(1)", "Sale of timber obtained by any other mode", 2, 2, 5, None, None, None, "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1) Sl. No. (vi)", "206C(1)", "Sale of scrap", 1, 1, 5, None, None, None, "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1) Sl. No. (vii)", "206C(1)", "Sale of coal, lignite or iron ore", 1, 1, 5, None, None, None, "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1C)", "206C(1C)", "Parking lot, toll plaza, mine or quarry licence", 2, 2, 5, None, None, None, "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1F)", "206C(1F)", "Sale of motor vehicles above the threshold", 1, 1, 5, 1000000, None, "per vehicle", "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1G)(a)", "206C(1G)", "LRS remittance for education or medical purposes", 5, 5, 10, None, 1000000, "excess over threshold", "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1G)(a)", "206C(1G)", "Other LRS remittances", 20, 20, 20, None, 1000000, "per tax year", "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1G)(b)", "206C(1G)", "Overseas tour packages up to ₹10 lakh", 5, 5, 10, None, 1000000, "up to ₹10 lakh", "gross", "2025-04-01", "2026-03-31"),
    ("tcs", 1961, "206C(1G)(b)", "206C(1G)", "Overseas tour packages above ₹10 lakh", 20, 20, 20, None, 1000000, "excess over threshold", "gross", "2025-04-01", "2026-03-31"),
    ("tds", 2025, "393(1) Sl. No. 6(i)", "194C", "Payment to contractor", 1, 2, 20, 30000, 100000, "per bill / tax year", "taxable", "2026-04-01", None),
    ("tds", 2025, "393(1) Sl. No. 1(ii)", "194H", "Commission or brokerage", 2, 2, 20, None, 20000, "per tax year", "taxable", "2026-04-01", None),
    ("tds", 2025, "393(1) Sl. No. 2(ii)(a)", "194-I", "Rent of plant, machinery or equipment", 2, 2, 20, 50000, None, "per month", "taxable", "2026-04-01", None),
    ("tds", 2025, "393(1) Sl. No. 2(ii)(b)", "194-I", "Rent of land, building or furniture", 10, 10, 20, 50000, None, "per month", "taxable", "2026-04-01", None),
    ("tds", 2025, "393(1) Sl. No. 6(iii)", "194J", "Fees for technical services, call centre or film royalty", 2, 2, 20, None, 50000, "per tax year", "taxable", "2026-04-01", None),
    ("tds", 2025, "393(1) Sl. No. 6(iii)", "194J", "Professional fees and other specified sums", 10, 10, 20, None, 50000, "per tax year", "taxable", "2026-04-01", None),
    ("tds", 2025, "393(1) Sl. No. 8(ii)", "194Q", "Purchase of goods above the annual threshold", 0.1, 0.1, 5, None, 5000000, "excess over threshold", "taxable", "2026-04-01", None),
    ("tds", 2025, "393(3) Sl. No. 7", "194T", "Payments to partners of a firm", 10, 10, 20, None, 20000, "per tax year", "taxable", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 1", "206C(1)", "Sale of alcoholic liquor for human consumption", 2, 2, 5, None, None, None, "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 2", "206C(1)", "Sale of tendu leaves", 2, 2, 5, None, None, None, "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 3", "206C(1)", "Sale of timber and other forest produce", 2, 2, 5, None, None, None, "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 4", "206C(1)", "Sale of scrap", 2, 2, 5, None, None, None, "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 5", "206C(1)", "Sale of coal, lignite or iron ore", 2, 2, 5, None, None, None, "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 6", "206C(1F)", "Sale of motor vehicles or notified goods above ₹10 lakh", 1, 1, 5, 1000000, None, "per transaction", "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 7", "206C(1G)", "LRS remittance for education or medical purposes", 2, 2, 5, None, 1000000, "per tax year", "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 7", "206C(1G)", "Other LRS remittances", 20, 20, 20, None, 1000000, "per tax year", "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 8", "206C(1G)", "Overseas tour packages", 2, 2, 5, None, None, None, "gross", "2026-04-01", None),
    ("tcs", 2025, "394(1) Sl. No. 9", "206C(1C)", "Parking lot, toll plaza, mine or quarry licence", 2, 2, 5, None, None, None, "gross", "2026-04-01", None),
]


def up(conn) -> None:
    conn.execute(text("ALTER TABLE buyers ADD COLUMN IF NOT EXISTS pan VARCHAR(10)"))
    conn.execute(text("ALTER TABLE buyers ADD COLUMN IF NOT EXISTS party_type VARCHAR(20)"))
    conn.execute(text("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS pan VARCHAR(10)"))
    conn.execute(text("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS tan VARCHAR(10)"))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS tax_withholding_sections (
            id SERIAL PRIMARY KEY,
            kind VARCHAR(3) NOT NULL CHECK (kind IN ('tds', 'tcs')),
            act INTEGER NOT NULL CHECK (act IN (1961, 2025)),
            section_ref VARCHAR(64) NOT NULL,
            legacy_code VARCHAR(16),
            nature VARCHAR(160) NOT NULL,
            rate_individual_huf NUMERIC(7,3) NOT NULL,
            rate_other NUMERIC(7,3) NOT NULL,
            rate_no_pan NUMERIC(7,3) NOT NULL,
            threshold_single NUMERIC(14,2),
            threshold_aggregate NUMERIC(14,2),
            threshold_note VARCHAR(32),
            base VARCHAR(16) NOT NULL CHECK (base IN ('taxable', 'gross')),
            effective_from DATE NOT NULL,
            effective_to DATE,
            CONSTRAINT uq_tax_withholding_section_version UNIQUE (kind, act, section_ref, nature, effective_from)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tax_withholding_sections_lookup ON tax_withholding_sections (kind, effective_from, effective_to)"))
    insert = text("""
        INSERT INTO tax_withholding_sections (
            kind, act, section_ref, legacy_code, nature, rate_individual_huf, rate_other,
            rate_no_pan, threshold_single, threshold_aggregate, threshold_note, base, effective_from, effective_to
        ) VALUES (
            :kind, :act, :section_ref, :legacy_code, :nature, :rate_individual_huf, :rate_other,
            :rate_no_pan, :threshold_single, :threshold_aggregate, :threshold_note, :base, :effective_from, :effective_to
        )
        ON CONFLICT (kind, act, section_ref, nature, effective_from) DO NOTHING
    """)
    keys = ("kind", "act", "section_ref", "legacy_code", "nature", "rate_individual_huf", "rate_other",
            "rate_no_pan", "threshold_single", "threshold_aggregate", "threshold_note", "base", "effective_from", "effective_to")
    for row in _SECTIONS:
        conn.execute(insert, dict(zip(keys, row)))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS tax_withholding_sections"))
    conn.execute(text("ALTER TABLE buyers DROP COLUMN IF EXISTS party_type"))
    conn.execute(text("ALTER TABLE buyers DROP COLUMN IF EXISTS pan"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS tan"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS pan"))
