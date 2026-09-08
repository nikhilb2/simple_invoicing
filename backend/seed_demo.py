"""Seed demo data for the invoicing application.

Wipes every table the demo owns (see _DEMO_TABLES) and recreates:

  * 1 company profile, made the admin's active company
  * 1 bank account (with a UPI id) + 1 cash account
  * 10 buyers / ledgers
  * 25 products with purchase prices and reorder levels
  * 100 sales invoices + 40 purchase invoices with 2-5 line items each
  * 50 payment receipts with invoice allocations
  * 11 credit / debit notes, outward and inward
  * a stock profile with real low-stock and out-of-stock items

Everything is written with an explicit company_id: the API filters every read
by the active company, so rows without one are invisible in the UI.

Usage:
    cd backend
    python seed_demo.py          # standalone
    python reset_db.py --with-demo   # full wipe + migrations + demo data
    make seed-demo               # via Docker
"""

import random
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text

from src.db.base import Base
from src.db.session import SessionLocal, engine
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.company_account import CompanyAccount
from src.models.credit_note import CreditNote, CreditNoteInvoiceRef, CreditNoteItem
from src.models.financial_year import FinancialYear  # noqa: F401 — needed for FK resolution
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.invoice_series import InvoiceSeries
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.models.product import Product
from src.models.user import User
from src.services.credit_note import _recompute_credit_status
from src.services.series import generate_next_number

random.seed(42)

TARGET_FY_LABEL = "2026-27"
TARGET_FY_START = date(2026, 4, 1)
TARGET_FY_END = date(2027, 3, 31)
SALES_INVOICE_COUNT = 100
PURCHASE_INVOICE_COUNT = 40

# The dashboard trend chart covers the last 12 calendar months, not the active
# financial year, so a database that only holds current-FY vouchers renders it
# with six empty columns. This prior year fills them, and gives the FY switcher
# a second year with real data behind it.
PRIOR_FY_LABEL = "2025-26"
PRIOR_FY_START = date(2025, 4, 1)
PRIOR_FY_END = date(2026, 3, 31)
PRIOR_SALES_INVOICE_COUNT = 45
PRIOR_PURCHASE_INVOICE_COUNT = 18

# ---------------------------------------------------------------------------
# Static demo data definitions
# ---------------------------------------------------------------------------

COMPANY = dict(
    name="Respawn Technologies Pvt Ltd",
    address="Unit 5, Pinnacle Tech Park, 5th Floor, Bannerghatta Road, Bengaluru 560 029",
    gst="29AAABB1234C1Z5",          # Karnataka state code 29
    phone_number="9876543210",
    currency_code="INR",
    email="accounts@respawn.in",
    website="https://www.respawn.in",
    bank_name="HDFC Bank",
    branch_name="Koramangala Branch",
    account_name="Respawn Technologies Pvt Ltd",
    account_number="50200012345678",
    ifsc_code="HDFC0001234",
)

# 3 Karnataka (intra-state), 7 other states (interstate), 1 with no GST
BUYERS = [
    dict(
        name="Apex Retail Solutions",
        address="12 MG Road, Bengaluru 560 001",
        gst="29AABCA1234D1Z3",
        phone_number="9845001001",
        email="finance@apexretail.in",
    ),
    dict(
        name="Zenith Traders",
        address="45 Anna Salai, Chennai 600 002",
        gst="33AABZT9876E1Z1",
        phone_number="9444001002",
        email="accounts@zenithtraders.in",
    ),
    dict(
        name="Nova Enterprises",
        address="8 Linking Road, Mumbai 400 050",
        gst="27AABNV5432F1Z2",
        phone_number="9833001003",
        email="bills@novae.in",
    ),
    dict(
        name="Horizon Distribution",
        address="22 Civil Lines, Pune 411 001",
        gst="27AABHD8765G1Z4",
        phone_number="9812001004",
        email="purchase@horizondist.in",
    ),
    dict(
        name="Pinnacle Goods Ltd",
        address="7 CP, New Delhi 110 001",
        gst="07AABPG4321H1Z5",
        phone_number="9811001005",
        email="finance@pinnaclegoods.in",
    ),
    dict(
        name="Stellar Corp",
        address="14 Hitech City, Hyderabad 500 081",
        gst="36AABSC7654I1Z6",
        phone_number="9966001006",
        email="accounts@stellarcorp.in",
    ),
    dict(
        name="Orbit Supplies Pvt Ltd",
        address="33 Salt Lake, Kolkata 700 064",
        gst="19AABOS3210J1Z7",
        phone_number="9830001007",
        email="bills@orbitsupplies.in",
    ),
    dict(
        name="Vertex Systems",
        address="56 Lavelle Road, Bengaluru 560 001",
        gst="29AABVS2109K1Z8",
        phone_number="9845001008",
        email="finance@vertexsys.in",
    ),
    dict(
        name="Prime IT Solutions",
        address="3 Connaught Place, New Delhi 110 001",
        gst="07AABPI6543L1Z9",
        phone_number="9899001009",
        email="accounts@primeit.in",
    ),
    dict(
        name="Nimbus Analytics",
        address="89 Koramangala, Bengaluru 560 034",
        gst=None,
        phone_number="9845001010",
        email="hello@nimbusanalytics.in",
    ),
]

PRODUCTS = [
    # purchase_price drives the dashboard "Stock value" card; reorder_level is
    # what makes a product count as low stock. Both were previously unset, which
    # left those two cards reading zero on a freshly seeded database.
    dict(sku="LAPTOP-01",   name='Business Laptop 15"',       description="Intel Core i7, 16 GB RAM, 512 GB SSD",   hsn_sac="84713010", price=65000.00, purchase_price=52000.00, gst_rate=18, reorder_level=15),
    dict(sku="LAPTOP-02",   name='Ultrabook 13"',              description="Ryzen 7, 16 GB RAM, 1 TB NVMe",          hsn_sac="84713010", price=72000.00, purchase_price=58500.00, gst_rate=18, reorder_level=12),
    dict(sku="MONITOR-01",  name='27" 4K Monitor',             description="IPS, 144 Hz, USB-C",                     hsn_sac="84713040", price=28000.00, purchase_price=21500.00, gst_rate=18, reorder_level=20),
    dict(sku="MONITOR-02",  name='24" FHD Monitor',            description="IPS, 75 Hz, HDMI+DP",                    hsn_sac="84713040", price=14500.00, purchase_price=11000.00, gst_rate=18, reorder_level=25),
    dict(sku="KEYBOARD-01", name="Mechanical Keyboard",        description="Cherry MX Red switches, TKL layout",     hsn_sac="84716060", price=4500.00,  purchase_price=3100.00,  gst_rate=18, reorder_level=40),
    dict(sku="MOUSE-01",    name="Wireless Mouse",             description="2.4 GHz, 4000 DPI, ergonomic",           hsn_sac="84716060", price=1800.00,  purchase_price=1150.00,  gst_rate=18, reorder_level=50),
    dict(sku="HEADSET-01",  name="Over-ear Headset",           description="Noise-cancelling, USB, mic included",    hsn_sac="85183000", price=5500.00,  purchase_price=3900.00,  gst_rate=18, reorder_level=30),
    dict(sku="WEBCAM-01",   name="Full HD Webcam",             description="1080p, built-in mic, USB",               hsn_sac="85258020", price=3200.00,  purchase_price=2150.00,  gst_rate=18, reorder_level=35),
    dict(sku="HDD-01",      name="1 TB External HDD",          description="USB 3.0, portable",                      hsn_sac="84717010", price=4200.00,  purchase_price=3050.00,  gst_rate=18, reorder_level=30),
    dict(sku="SSD-01",      name="512 GB SSD",                 description="SATA III, 2.5 inch",                     hsn_sac="84717010", price=5800.00,  purchase_price=4300.00,  gst_rate=12, reorder_level=30),
    dict(sku="RAM-01",      name="16 GB DDR4 RAM",             description="3200 MHz, single stick",                 hsn_sac="84717010", price=3500.00,  purchase_price=2450.00,  gst_rate=12, reorder_level=40),
    dict(sku="ROUTER-01",   name="Wi-Fi 6 Router",             description="Dual-band, AX3000",                      hsn_sac="85176200", price=6800.00,  purchase_price=4900.00,  gst_rate=18, reorder_level=25),
    dict(sku="SWITCH-01",   name="8-Port Network Switch",      description="Gigabit, unmanaged",                     hsn_sac="85176200", price=2400.00,  purchase_price=1600.00,  gst_rate=18, reorder_level=30),
    dict(sku="HDMI-01",     name="HDMI 2.0 Cable 2m",          description="4K@60Hz, gold-plated connectors",        hsn_sac="85444290", price=450.00,   purchase_price=240.00,   gst_rate=18, reorder_level=100),
    dict(sku="USBC-01",     name="USB-C Cable 1m",             description="100W PD, Gen 2",                         hsn_sac="85444290", price=650.00,   purchase_price=360.00,   gst_rate=18, reorder_level=100),
    dict(sku="CHARGER-01",  name="65W GaN Charger",            description="USB-C, 3-port",                          hsn_sac="85044030", price=2200.00,  purchase_price=1450.00,  gst_rate=18, reorder_level=45),
    dict(sku="BAG-01",      name='15" Laptop Bag',             description="Water-resistant, multiple compartments", hsn_sac="42021200", price=1200.00,  purchase_price=720.00,   gst_rate=12, reorder_level=60),
    dict(sku="STAND-01",    name="Adjustable Laptop Stand",    description="Aluminium, 6 heights",                   hsn_sac="94039000", price=2800.00,  purchase_price=1850.00,  gst_rate=18, reorder_level=35),
    dict(sku="DOCK-01",     name="USB-C Docking Station",      description="10-in-1, 4K60Hz dual display",           hsn_sac="84733020", price=8500.00,  purchase_price=6200.00,  gst_rate=18, reorder_level=20),
    dict(sku="UPS-01",      name="600 VA UPS",                 description="Line-interactive, 10 min backup",        hsn_sac="85044040", price=4600.00,  purchase_price=3300.00,  gst_rate=18, reorder_level=25),
    dict(sku="PRINTER-01",  name="Laser Printer A4",           description="Mono, 30 ppm, network",                  hsn_sac="84433200", price=18000.00, purchase_price=13800.00, gst_rate=18, reorder_level=10),
    dict(sku="TONER-01",    name="Laser Toner Cartridge",      description="Compatible, 5000 pages",                 hsn_sac="84439980", price=1800.00,  purchase_price=1050.00,  gst_rate=18, reorder_level=50),
    dict(sku="PAPER-01",    name="A4 Copier Paper (500 sheets)", description="80 gsm, bright white",                 hsn_sac="48025590", price=320.00,   purchase_price=195.00,   gst_rate=12, reorder_level=120),
    # Licence keys and pre-paid support packs. Stocked like any other line:
    # /api/inventory/ lists every product regardless of maintain_inventory, so a
    # non-stocked item shows up as "0 units" and sorts to the top of the
    # dashboard's low-stock panel as though it had run out.
    dict(sku="AV-01",       name="Antivirus 1-Year License",   description="3 devices, cloud backup included",       hsn_sac="99831190", price=1200.00,  purchase_price=780.00,   gst_rate=18, reorder_level=40),
    dict(sku="AMC-01",      name="Annual Maintenance Contract", description="On-site support, 4-hr SLA",             hsn_sac="99831190", price=12000.00, purchase_price=7500.00,  gst_rate=18, reorder_level=8),
]

# ---------------------------------------------------------------------------
# Internal helpers (mirrors logic in src/api/routes/invoices.py)
# ---------------------------------------------------------------------------

def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_interstate(company_gst: str | None, buyer_gst: str | None) -> bool:
    """Return True when the two GSTIN state codes differ (triggers IGST instead of CGST/SGST)."""
    if not company_gst or not buyer_gst or len(company_gst) < 2 or len(buyer_gst) < 2:
        return False
    return company_gst[:2] != buyer_gst[:2]


def _ensure_target_financial_year(db, company_id: int) -> FinancialYear:
    """Create/activate FY 2026-27 for this company and return it."""
    fy = (
        db.query(FinancialYear)
        .filter(
            FinancialYear.label == TARGET_FY_LABEL,
            FinancialYear.company_id == company_id,
        )
        .first()
    )
    if fy is None:
        fy = FinancialYear(
            label=TARGET_FY_LABEL,
            start_date=TARGET_FY_START,
            end_date=TARGET_FY_END,
            is_active=True,
            company_id=company_id,
        )
        db.add(fy)
    else:
        fy.start_date = TARGET_FY_START
        fy.end_date = TARGET_FY_END
        fy.is_active = True

    db.query(FinancialYear).filter(
        FinancialYear.label != TARGET_FY_LABEL,
        FinancialYear.company_id == company_id,
    ).update(
        {"is_active": False},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(fy)
    return fy


def _ensure_prior_financial_year(db, company_id: int) -> FinancialYear:
    """Create (inactive) FY 2025-26 so last year's vouchers have a home."""
    fy = FinancialYear(
        label=PRIOR_FY_LABEL,
        start_date=PRIOR_FY_START,
        end_date=PRIOR_FY_END,
        is_active=False,
        company_id=company_id,
    )
    db.add(fy)
    db.commit()
    db.refresh(fy)
    return fy


def _ensure_series_for_financial_year(db, fy: FinancialYear, company_id: int) -> None:
    """Ensure FY-scoped numbering series exists for every voucher type we seed.

    generate_next_number() rejects a series whose company_id doesn't match the
    one it is called with, so these rows have to carry the company or every
    document falls back to the INV-000000 emergency sequence.
    """
    defaults = {
        "sales": "INV",
        "purchase": "PINV",
        "payment": "PAY",
        "credit_note": "CN",
        "debit_note": "DN",
    }

    for voucher_type, default_prefix in defaults.items():
        existing = (
            db.query(InvoiceSeries)
            .filter(
                InvoiceSeries.voucher_type == voucher_type,
                InvoiceSeries.financial_year_id == fy.id,
            )
            .first()
        )
        if existing:
            # A migration may have seeded this row before the company existed.
            existing.company_id = company_id
            existing.next_sequence = 1
            continue

        # Clone format settings from any existing series for this voucher type.
        # If none exists, create a sensible default so generate_next_number()
        # never falls back to INV-000000/PAY-000000.
        template = (
            db.query(InvoiceSeries)
            .filter(InvoiceSeries.voucher_type == voucher_type)
            .order_by(InvoiceSeries.id.asc())
            .first()
        )

        if template is not None:
            series = InvoiceSeries(
                voucher_type=voucher_type,
                financial_year_id=fy.id,
                company_id=company_id,
                prefix=template.prefix,
                suffix=template.suffix,
                include_year=template.include_year,
                year_format=template.year_format,
                separator=template.separator,
                next_sequence=1,
                pad_digits=template.pad_digits,
            )
        else:
            series = InvoiceSeries(
                voucher_type=voucher_type,
                financial_year_id=fy.id,
                company_id=company_id,
                prefix=default_prefix,
                suffix="",
                include_year=True,
                year_format="YYYY",
                separator="-",
                next_sequence=1,
                pad_digits=3,
            )
        db.add(series)

    db.commit()


# ---------------------------------------------------------------------------
# Deletion — reverse FK dependency order
# ---------------------------------------------------------------------------

# Everything the demo owns, in one TRUNCATE. Listing the tables explicitly
# rather than using CASCADE is deliberate: users.active_company_id references
# company_profiles, so a CASCADE from there would take the admin account with
# it. Config the demo does not own — users, smtp_configs, global_settings,
# user_shortcuts, _migrations — is left alone.
#
# company_profiles is absent on purpose. Postgres refuses to TRUNCATE a table
# that any foreign key references, even from an empty table, so it is cleared
# with a DELETE once the rows pointing at it are released.
_DEMO_TABLES = (
    "payment_invoice_allocations",
    "payments",
    "credit_note_items",
    "credit_note_invoice_refs",
    "credit_notes",
    "marketplace_order_items",
    "marketplace_orders",
    "marketplace_processed_events",
    "marketplace_listings",
    "marketplace_product_links",
    "marketplace_ledger_links",
    "marketplace_connections",
    "share_links",
    "email_logs",
    "invoice_items",
    "invoices",
    "production_transactions",
    "bill_of_materials",
    "product_serials",
    "inventory",
    "products",
    "company_accounts",
    "ledger_addresses",
    "buyers",
    "company_terms",
    "invoice_series",
    "financial_years",
)


def _delete_demo_data(db) -> None:
    print("  Deleting existing data...")
    db.execute(
        text("TRUNCATE TABLE {} RESTART IDENTITY".format(", ".join(_DEMO_TABLES)))
    )

    # Release every remaining reference into company_profiles. An API key is
    # NOT NULL on company_id — a key scoped to a company that no longer exists
    # cannot authenticate anything, so it goes with it.
    db.execute(text("UPDATE users SET active_company_id = NULL"))
    db.execute(text("UPDATE oauth_tokens SET company_id = NULL"))
    db.execute(text("UPDATE oauth_authorization_codes SET company_id = NULL"))
    db.execute(text("DELETE FROM api_keys"))

    db.execute(text("DELETE FROM company_profiles"))
    db.execute(text("ALTER SEQUENCE company_profiles_id_seq RESTART WITH 1"))
    db.commit()
    print("  Done.")


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------

def _seed_company(db) -> CompanyProfile:
    company = CompanyProfile(**COMPANY)
    db.add(company)
    db.commit()
    db.refresh(company)
    print(f"  Company: {company.name}")
    return company


def _seed_accounts(db, admin_id: int, company_id: int) -> tuple:
    bank = CompanyAccount(
        company_id=company_id,
        account_type="bank",
        display_name="HDFC Current Account",
        bank_name="HDFC Bank",
        branch_name="Koramangala Branch",
        account_name="Respawn Technologies Pvt Ltd",
        account_number="50200012345678",
        ifsc_code="HDFC0001234",
        upi_vpa="respawn@hdfcbank",
        display_on_invoice=True,
        opening_balance=Decimal("500000.00"),
        is_active=True,
        created_by=admin_id,
    )
    cash = CompanyAccount(
        company_id=company_id,
        account_type="cash",
        display_name="Petty Cash",
        display_on_invoice=False,
        opening_balance=Decimal("25000.00"),
        is_active=True,
        created_by=admin_id,
    )
    db.add_all([bank, cash])
    db.commit()
    db.refresh(bank)
    db.refresh(cash)
    print(f"  Accounts: {bank.display_name}, {cash.display_name}")
    return bank, cash


def _seed_buyers(db, company_id: int) -> list:
    buyers = []
    for data in BUYERS:
        b = Buyer(**data, company_id=company_id)
        db.add(b)
        buyers.append(b)
    db.commit()
    for b in buyers:
        db.refresh(b)
    print(f"  Buyers: {len(buyers)}")
    return buyers


def _seed_products(db, company_id: int) -> list:
    """Create products and paired inventory rows (500 units each)."""
    products = []
    for data in PRODUCTS:
        p = Product(**data, company_id=company_id)
        db.add(p)
        db.flush()
        if p.maintain_inventory:
            db.add(Inventory(product_id=p.id, quantity=500, company_id=company_id))
        products.append(p)
    db.commit()
    for p in products:
        db.refresh(p)
    print(f"  Products: {len(products)} (each seeded with 500 units)")
    return products


def _seed_invoices(
    db,
    admin_id: int,
    company: CompanyProfile,
    buyers: list,
    products: list,
    fy,
    count: int = SALES_INVOICE_COUNT,
    historic: bool = False,
) -> tuple[list, set[int]]:
    """Create sales invoices inside `fy`.

    `historic=True` seeds a closed year: every invoice gets an ordinary due date
    inside the year and none are reserved as unpaid, because last year's
    receivables should not still be sitting on today's dashboard.
    """
    fy_id = fy.id if fy else None
    today = date.today()
    invoices = []
    protected_due_invoice_ids: set[int] = set()

    # Keep invoice dates inside the target financial year.
    date_floor = fy.start_date if fy else TARGET_FY_START
    date_ceiling = min(today, fy.end_date) if fy else today

    if historic:
        # Only the part of the closed year that the dashboard's rolling
        # 12-month chart actually renders — spreading 45 invoices over a full
        # year would leave those columns looking sparse.
        date_floor = max(date_floor, today - timedelta(days=360))

    if date_ceiling < date_floor:
        date_ceiling = date_floor

    # The list endpoint orders by id descending, so creation order is display
    # order. Building every date first and sorting them means invoice numbers
    # ascend with invoice date, the way a real numbering series does — and the
    # dashboard's "latest activity" panel shows the genuinely latest invoices.
    schedule: list[tuple[date, date | None]] = []
    spread_days = max((date_ceiling - date_floor).days, 0)
    for i in range(count):
        invoice_date = date_floor + timedelta(days=random.randint(0, spread_days))

        # Guarantee some overdue invoices with pending balances for the Due Invoices page.
        due_date = None
        if historic:
            due_date = min(fy.end_date, invoice_date + timedelta(days=random.randint(15, 45)))
        elif i < 28:
            # Genuinely late: due date already behind us.
            overdue_days = random.randint(5, 45)
            due_base = today - timedelta(days=overdue_days)
            due_base = max(date_floor, min(due_base, date_ceiling))
            invoice_date = max(date_floor, due_base - timedelta(days=random.randint(5, 25)))
            due_date = due_base
        elif i < 70:
            # Upcoming, not overdue — forced past today so a randomly early
            # invoice date can't quietly land these in the overdue bucket too.
            lead_days = random.randint(7, 45)
            due_date = min(
                fy.end_date,
                max(invoice_date + timedelta(days=lead_days), today + timedelta(days=random.randint(3, 40))),
            )
        schedule.append((invoice_date, due_date))

    schedule.sort(key=lambda pair: pair[0])

    for i, (invoice_date, due_date) in enumerate(schedule):
        buyer = random.choice(buyers)
        selected = random.sample(products, random.randint(2, 5))
        interstate = _is_interstate(company.gst, buyer.gst)

        invoice = Invoice(
            total_amount=0,
            created_by=admin_id,
            company_id=company.id,
            financial_year_id=fy_id,
            invoice_date=datetime.combine(invoice_date, datetime.min.time()),
            due_date=datetime.combine(due_date, datetime.min.time()) if due_date is not None else None,
            # Buyer snapshot
            ledger_id=buyer.id,
            ledger_name=buyer.name,
            ledger_address=buyer.address,
            ledger_gst=buyer.gst,
            ledger_phone=buyer.phone_number,
            # Company snapshot
            company_name=company.name,
            company_address=company.address,
            company_gst=company.gst,
            company_phone=company.phone_number,
            company_email=company.email,
            company_website=company.website,
            company_currency_code=company.currency_code,
            company_bank_name=company.bank_name,
            company_branch_name=company.branch_name,
            company_account_name=company.account_name,
            company_account_number=company.account_number,
            company_ifsc_code=company.ifsc_code,
            voucher_type="sales",
            tax_inclusive=False,
            apply_round_off=False,
            round_off_amount=0.0,
        )
        db.add(invoice)
        db.flush()  # Populate invoice.id before creating items

        # Generate unique invoice number (atomically increments InvoiceSeries counter)
        invoice.invoice_number = generate_next_number(
            db, "sales", fy_id, invoice_date, company_id=company.id
        )

        # Build line items
        taxable_total = Decimal("0")
        items: list[InvoiceItem] = []

        for product in selected:
            qty = random.randint(1, 5)
            unit_price = Decimal(str(product.price))
            gst_rate = Decimal(str(product.gst_rate or 0))
            taxable = _money(unit_price * qty)
            tax = _money(taxable * gst_rate / Decimal("100"))

            if interstate:
                cgst, sgst, igst = 0.0, 0.0, float(tax)
            else:
                half = float(_money(tax / Decimal("2")))
                cgst, sgst, igst = half, half, 0.0

            item = InvoiceItem(
                invoice_id=invoice.id,
                product_id=product.id,
                quantity=qty,
                hsn_sac=product.hsn_sac,
                unit_price=float(unit_price),
                gst_rate=float(gst_rate),
                taxable_amount=float(taxable),
                tax_amount=float(tax),
                cgst_amount=cgst,
                sgst_amount=sgst,
                igst_amount=igst,
                line_total=float(_money(taxable + tax)),
            )
            items.append(item)
            taxable_total += taxable

            # Directly decrement inventory (quantities are well within the 500-unit buffer)
            inv = (
                db.query(Inventory)
                .filter(
                    Inventory.product_id == product.id,
                    Inventory.company_id == company.id,
                )
                .first()
            )
            if inv:
                inv.quantity = max(0, inv.quantity - qty)

        db.add_all(items)

        # Roll up invoice totals
        taxable_total = _money(taxable_total)
        cgst_total = _money(sum(Decimal(str(it.cgst_amount or 0)) for it in items))
        sgst_total = _money(sum(Decimal(str(it.sgst_amount or 0)) for it in items))
        igst_total = _money(sum(Decimal(str(it.igst_amount or 0)) for it in items))
        tax_total = _money(cgst_total + sgst_total + igst_total)

        invoice.taxable_amount = float(taxable_total)
        invoice.total_tax_amount = float(tax_total)
        invoice.cgst_amount = float(cgst_total)
        invoice.sgst_amount = float(sgst_total)
        invoice.igst_amount = float(igst_total)
        invoice.total_amount = float(_money(taxable_total + tax_total))

        invoices.append(invoice)

        if not historic and i < 20:
            protected_due_invoice_ids.add(invoice.id)

        if (i + 1) % 25 == 0:
            db.commit()
            print(f"    {i + 1}/{count} sales invoices committed")

    db.commit()
    for inv in invoices:
        db.refresh(inv)
    return invoices, protected_due_invoice_ids


def _seed_purchase_invoices(
    db,
    admin_id: int,
    company: CompanyProfile,
    buyers: list,
    products: list,
    fy,
    count: int = PURCHASE_INVOICE_COUNT,
) -> list:
    fy_id = fy.id if fy else None
    today = date.today()
    invoices = []

    date_floor = fy.start_date if fy else TARGET_FY_START
    date_ceiling = min(today, fy.end_date) if fy else today
    if date_ceiling < date_floor:
        date_ceiling = date_floor

    spread_days = max((date_ceiling - date_floor).days, 0)
    purchase_dates = sorted(
        date_floor + timedelta(days=random.randint(0, spread_days)) for _ in range(count)
    )

    for i, invoice_date in enumerate(purchase_dates):
        vendor = random.choice(buyers)
        selected = random.sample(products, random.randint(2, 5))
        interstate = _is_interstate(company.gst, vendor.gst)

        due_date = min(fy.end_date, invoice_date + timedelta(days=random.randint(15, 45)))

        invoice = Invoice(
            total_amount=0,
            created_by=admin_id,
            company_id=company.id,
            financial_year_id=fy_id,
            invoice_date=datetime.combine(invoice_date, datetime.min.time()),
            due_date=datetime.combine(due_date, datetime.min.time()),
            ledger_id=vendor.id,
            ledger_name=vendor.name,
            ledger_address=vendor.address,
            ledger_gst=vendor.gst,
            ledger_phone=vendor.phone_number,
            company_name=company.name,
            company_address=company.address,
            company_gst=company.gst,
            company_phone=company.phone_number,
            company_email=company.email,
            company_website=company.website,
            company_currency_code=company.currency_code,
            company_bank_name=company.bank_name,
            company_branch_name=company.branch_name,
            company_account_name=company.account_name,
            company_account_number=company.account_number,
            company_ifsc_code=company.ifsc_code,
            voucher_type="purchase",
            supplier_invoice_number=f"SUP-{fy.label}-{i + 1:04d}",
            tax_inclusive=False,
            apply_round_off=False,
            round_off_amount=0.0,
        )
        db.add(invoice)
        db.flush()

        invoice.invoice_number = generate_next_number(
            db, "purchase", fy_id, invoice_date, company_id=company.id
        )

        taxable_total = Decimal("0")
        items: list[InvoiceItem] = []

        for product in selected:
            # Bought at cost, not at the price we resell for, and in restock-sized
            # quantities — otherwise total purchases dwarf total sales.
            qty = random.randint(2, 8)
            unit_price = Decimal(str(product.purchase_price or product.price))
            gst_rate = Decimal(str(product.gst_rate or 0))
            taxable = _money(unit_price * qty)
            tax = _money(taxable * gst_rate / Decimal("100"))

            if interstate:
                cgst, sgst, igst = 0.0, 0.0, float(tax)
            else:
                half = float(_money(tax / Decimal("2")))
                cgst, sgst, igst = half, half, 0.0

            item = InvoiceItem(
                invoice_id=invoice.id,
                product_id=product.id,
                quantity=qty,
                hsn_sac=product.hsn_sac,
                unit_price=float(unit_price),
                gst_rate=float(gst_rate),
                taxable_amount=float(taxable),
                tax_amount=float(tax),
                cgst_amount=cgst,
                sgst_amount=sgst,
                igst_amount=igst,
                line_total=float(_money(taxable + tax)),
            )
            items.append(item)
            taxable_total += taxable

            # Purchase vouchers restock inventory.
            inv = (
                db.query(Inventory)
                .filter(
                    Inventory.product_id == product.id,
                    Inventory.company_id == company.id,
                )
                .first()
            )
            if inv:
                inv.quantity += qty

        db.add_all(items)

        taxable_total = _money(taxable_total)
        cgst_total = _money(sum(Decimal(str(it.cgst_amount or 0)) for it in items))
        sgst_total = _money(sum(Decimal(str(it.sgst_amount or 0)) for it in items))
        igst_total = _money(sum(Decimal(str(it.igst_amount or 0)) for it in items))
        tax_total = _money(cgst_total + sgst_total + igst_total)

        invoice.taxable_amount = float(taxable_total)
        invoice.total_tax_amount = float(tax_total)
        invoice.cgst_amount = float(cgst_total)
        invoice.sgst_amount = float(sgst_total)
        invoice.igst_amount = float(igst_total)
        invoice.total_amount = float(_money(taxable_total + tax_total))

        invoices.append(invoice)

        if (i + 1) % 20 == 0:
            db.commit()
            print(f"    {i + 1}/{count} purchase invoices committed")

    db.commit()
    for inv in invoices:
        db.refresh(inv)
    return invoices


def _seed_receipts(
    db,
    admin_id: int,
    company_id: int,
    buyers: list,
    invoices: list,
    bank_acc: CompanyAccount,
    fy,
    excluded_invoice_ids: set[int],
    count: int = 50,
    settle_fully: bool = False,
) -> list:
    """Record customer receipts against `invoices`.

    `settle_fully` clears the whole outstanding balance, which is what a closed
    prior year should look like; the current year leaves partial balances so the
    receivables panels have something to show.
    """
    fy_id = fy.id if fy else None
    today = date.today()

    # Index invoices by ledger_id for quick lookup
    by_buyer: dict[int, list] = {}
    for inv in invoices:
        by_buyer.setdefault(inv.ledger_id, []).append(inv)

    # Track remaining unallocated balance per invoice
    remaining: dict[int, Decimal] = {
        inv.id: _money(Decimal(str(inv.total_amount))) for inv in invoices
    }

    buyers_with_invoices = [b for b in buyers if b.id in by_buyer]
    receipts: list[Payment] = []
    attempts = 0

    while len(receipts) < count and attempts < count * 3:
        attempts += 1
        buyer = random.choice(buyers_with_invoices)

        # Only consider invoices that still have an outstanding balance
        candidates = [
            inv for inv in by_buyer[buyer.id]
            if remaining[inv.id] > Decimal("0.01") and inv.id not in excluded_invoice_ids
        ]
        if not candidates:
            continue

        chosen = random.sample(candidates, min(len(candidates), random.randint(1, 3)))
        total = Decimal("0")
        allocs: list[tuple[int, Decimal]] = []

        for inv in chosen:
            rem = remaining[inv.id]
            # Pay between 40 % and 100 % of the remaining balance
            ratio = Decimal("1") if settle_fully else Decimal(str(round(random.uniform(0.4, 1.0), 4)))
            alloc = _money(rem * ratio)
            alloc = min(alloc, rem)
            if alloc <= 0:
                continue
            total += alloc
            allocs.append((inv.id, alloc))
            remaining[inv.id] = _money(rem - alloc)

        if total <= 0 or not allocs:
            continue

        # Never before the newest invoice being settled, and never past the end
        # of the year the receipt belongs to. Spreading across the whole year
        # rather than the last 90 days keeps the trend chart's receipts series
        # from flatlining in the early months.
        earliest = max(inv.invoice_date.date() for inv in chosen)
        latest = fy.end_date if settle_fully else min(today, fy.end_date)
        if latest < earliest:
            latest = earliest
        pmt_date = earliest + timedelta(days=random.randint(0, (latest - earliest).days))
        payment = Payment(
            ledger_id=buyer.id,
            company_id=company_id,
            voucher_type="receipt",
            amount=float(total),
            date=datetime.combine(pmt_date, datetime.min.time()),
            mode=random.choice(["bank", "bank", "upi", "cheque"]),
            financial_year_id=fy_id,
            account_id=bank_acc.id,
            created_by=admin_id,
            status="active",
        )
        db.add(payment)
        db.flush()

        payment.payment_number = generate_next_number(
            db, "payment", fy_id, pmt_date, company_id=company_id
        )

        for inv_id, alloc_amount in allocs:
            db.add(PaymentInvoiceAllocation(
                payment_id=payment.id,
                invoice_id=inv_id,
                allocated_amount=float(alloc_amount),
            ))

        receipts.append(payment)

        if len(receipts) % 10 == 0:
            db.commit()
            print(f"    {len(receipts)}/{count} receipts committed")

    db.commit()
    print(f"  Receipts: {len(receipts)}")
    return receipts



def _seed_credit_notes(
    db,
    admin_id: int,
    company: CompanyProfile,
    sales_invoices: list,
    purchase_invoices: list,
    fy,
    excluded_invoice_ids: set[int],
) -> list:
    """Issue a handful of notes in both directions.

    Mirrors src/services/credit_note.py: an outward note credits a sales
    invoice and puts the units back on the shelf; an inward one records the
    supplier's note against a purchase and takes them off again. Invoices
    reserved for the dues page are skipped so their outstanding balance stays
    the number the dashboard is meant to show.
    """
    fy_id = fy.id if fy else None
    notes: list[CreditNote] = []

    plan = [
        (inv, "outward", "sales")
        for inv in sales_invoices
        if inv.id not in excluded_invoice_ids
    ][:8]
    plan += [(inv, "inward", "purchase") for inv in purchase_invoices][:3]

    reasons_out = [
        "Damaged in transit",
        "Wrong model shipped",
        "Short shipment adjustment",
        "Customer returned unopened stock",
    ]
    reasons_in = [
        "Supplier short-supplied against PO",
        "Defective units returned to supplier",
    ]

    for index, (invoice, direction, source) in enumerate(plan):
        items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).all()
        if not items:
            continue

        source_item = items[index % len(items)]
        qty = max(1, min(int(source_item.quantity), 2))
        unit_price = Decimal(str(source_item.unit_price))
        gst_rate = Decimal(str(source_item.gst_rate or 0))
        taxable = _money(unit_price * qty)
        tax = _money(taxable * gst_rate / Decimal("100"))

        interstate = _is_interstate(invoice.company_gst, invoice.ledger_gst)
        if interstate:
            cgst = sgst = Decimal("0")
            igst = tax
        else:
            cgst = sgst = _money(tax / Decimal("2"))
            igst = Decimal("0")
            tax = _money(cgst + sgst)

        line_total = _money(taxable + tax)
        cn_date = invoice.invoice_date.date() + timedelta(days=random.randint(3, 20))
        cn_date = min(cn_date, min(date.today(), TARGET_FY_END))

        cn = CreditNote(
            credit_note_number=generate_next_number(
                db,
                "debit_note" if direction == "inward" else "credit_note",
                fy_id,
                cn_date,
                company_id=company.id,
            ),
            company_id=company.id,
            ledger_id=invoice.ledger_id,
            financial_year_id=fy_id,
            created_by=admin_id,
            credit_note_type="return",
            direction=direction,
            supplier_credit_note_number=(
                f"SCN-{TARGET_FY_LABEL}-{index + 1:03d}" if direction == "inward" else None
            ),
            supplier_credit_note_date=cn_date if direction == "inward" else None,
            reason=(
                random.choice(reasons_in) if direction == "inward" else random.choice(reasons_out)
            ),
            status="active",
            taxable_amount=taxable,
            cgst_amount=cgst,
            sgst_amount=sgst,
            igst_amount=igst,
            total_amount=line_total,
            created_at=datetime.combine(cn_date, datetime.min.time()),
        )
        db.add(cn)
        db.flush()

        db.add(CreditNoteInvoiceRef(credit_note_id=cn.id, invoice_id=invoice.id))
        db.add(CreditNoteItem(
            credit_note_id=cn.id,
            company_id=company.id,
            invoice_id=invoice.id,
            invoice_item_id=source_item.id,
            product_id=source_item.product_id,
            quantity=qty,
            unit_price=unit_price,
            gst_rate=gst_rate,
            taxable_amount=taxable,
            tax_amount=tax,
            line_total=line_total,
        ))

        # A return undoes what its invoice did to stock.
        inv_row = (
            db.query(Inventory)
            .filter(
                Inventory.product_id == source_item.product_id,
                Inventory.company_id == company.id,
            )
            .first()
        )
        if inv_row is not None:
            delta = qty if source == "sales" else -qty
            inv_row.quantity = max(0, int(inv_row.quantity) + delta)

        notes.append(cn)

    db.commit()

    # Keep invoice.credit_status consistent with what the app would compute.
    for cn in notes:
        for ref in db.query(CreditNoteInvoiceRef).filter(
            CreditNoteInvoiceRef.credit_note_id == cn.id
        ):
            _recompute_credit_status(ref.invoice_id, db, company_id=company.id)
    db.commit()

    print(f"  Credit / debit notes: {len(notes)}")
    return notes


def _apply_stock_profile(db, company_id: int, products: list) -> None:
    """Give the shelf a believable spread instead of ~500 of everything.

    The dashboard's low-stock card and the "Inventory pressure points" panel
    both stay empty until some product is actually under its reorder level, so
    a flat 500 units makes two of the dashboard's panels look broken.
    """
    stocked = [p for p in products if p.maintain_inventory]
    out_of_stock = {"TONER-01", "HDMI-01"}
    low_stock = {"MONITOR-02", "MOUSE-01", "DOCK-01", "UPS-01"}

    for product in stocked:
        row = (
            db.query(Inventory)
            .filter(
                Inventory.product_id == product.id,
                Inventory.company_id == company_id,
            )
            .first()
        )
        if row is None:
            continue

        reorder = int(product.reorder_level or 0)
        if product.sku in out_of_stock:
            row.quantity = 0
        elif product.sku in low_stock:
            # At or under the reorder level, but never negative.
            row.quantity = max(1, reorder - random.randint(0, max(reorder // 3, 1)))
        else:
            # Comfortable cover: two to eight times the reorder level.
            base = reorder if reorder > 0 else 20
            row.quantity = base * random.randint(2, 8)

    db.commit()
    print(
        f"  Stock profile: {len(out_of_stock)} out of stock, "
        f"{len(low_stock)} below reorder level"
    )



def _seed_supplier_payments(
    db,
    admin_id: int,
    company_id: int,
    purchase_invoices: list,
    bank_acc: CompanyAccount,
    fy,
    count: int = 22,
) -> list:
    """Pay some suppliers.

    Without these the dashboard's "paid" figure and the outgoing side of Cash &
    Bank both sit at zero, which makes the business look like it never settles
    a bill.
    """
    fy_id = fy.id if fy else None
    today = date.today()
    payments: list[Payment] = []

    candidates = list(purchase_invoices)
    random.shuffle(candidates)

    for invoice in candidates[:count]:
        # Most bills settled in full, a few part-paid.
        total = _money(Decimal(str(invoice.total_amount)))
        if random.random() < 0.25:
            total = _money(total * Decimal(str(round(random.uniform(0.35, 0.8), 4))))
        if total <= 0:
            continue

        earliest = invoice.invoice_date.date()
        latest = min(today, fy.end_date)
        if latest < earliest:
            latest = earliest
        pmt_date = earliest + timedelta(days=random.randint(0, max((latest - earliest).days, 0)))

        payment = Payment(
            ledger_id=invoice.ledger_id,
            company_id=company_id,
            voucher_type="payment",
            amount=float(total),
            date=datetime.combine(pmt_date, datetime.min.time()),
            mode=random.choice(["bank", "bank", "upi", "cheque"]),
            financial_year_id=fy_id,
            account_id=bank_acc.id,
            created_by=admin_id,
            status="active",
        )
        db.add(payment)
        db.flush()
        payment.payment_number = generate_next_number(
            db, "payment", fy_id, pmt_date, company_id=company_id
        )
        db.add(PaymentInvoiceAllocation(
            payment_id=payment.id,
            invoice_id=invoice.id,
            allocated_amount=float(total),
        ))
        payments.append(payment)

    db.commit()
    print(f"  Supplier payments: {len(payments)}")
    return payments


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def seed_all(db) -> None:
    admin = db.query(User).filter(User.email == "admin@simple.dev").first()
    if not admin:
        print("ERROR: Admin user not found. Run `python seed_admin.py` first.")
        sys.exit(1)

    # Order matters: everything below is company-scoped, so the company has to
    # exist before the financial year, the numbering series, or any voucher.
    _delete_demo_data(db)

    company = _seed_company(db)

    # Without this the API resolves no active company and every page reads empty.
    admin.active_company_id = company.id
    db.commit()

    fy = _ensure_target_financial_year(db, company.id)
    print(f"  Active financial year forced to: {fy.label} ({fy.start_date} to {fy.end_date})")
    _ensure_series_for_financial_year(db, fy, company.id)

    bank_acc, _cash_acc = _seed_accounts(db, admin.id, company.id)
    buyers = _seed_buyers(db, company.id)
    products = _seed_products(db, company.id)

    # Chronological order: last year is entered before this year, and within a
    # year purchases before sales. The invoice list orders by id descending, so
    # this is what puts recent sales invoices at the top of "latest activity"
    # instead of prior-year purchase vouchers.
    print(f"  Creating {PRIOR_FY_LABEL} history...")
    prior_fy = _ensure_prior_financial_year(db, company.id)
    _ensure_series_for_financial_year(db, prior_fy, company.id)
    prior_purchases = _seed_purchase_invoices(
        db, admin.id, company, buyers, products, prior_fy,
        count=PRIOR_PURCHASE_INVOICE_COUNT,
    )
    prior_sales, _ = _seed_invoices(
        db, admin.id, company, buyers, products, prior_fy,
        count=PRIOR_SALES_INVOICE_COUNT, historic=True,
    )
    _seed_receipts(
        db, admin.id, company.id, buyers, prior_sales, bank_acc, prior_fy, set(),
        count=PRIOR_SALES_INVOICE_COUNT, settle_fully=True,
    )
    _seed_supplier_payments(
        db, admin.id, company.id, prior_purchases, bank_acc, prior_fy,
        count=PRIOR_PURCHASE_INVOICE_COUNT,
    )
    print(f"  Prior year: {len(prior_sales)} sales, {len(prior_purchases)} purchases")

    print("  Creating purchase invoices...")
    purchase_invoices = _seed_purchase_invoices(db, admin.id, company, buyers, products, fy)
    print(f"  Purchase invoices: {len(purchase_invoices)}")

    print("  Creating invoices...")
    invoices, protected_due_invoice_ids = _seed_invoices(db, admin.id, company, buyers, products, fy)
    print(f"  Sales invoices: {len(invoices)}")

    print("  Creating receipts...")
    _seed_receipts(
        db, admin.id, company.id, buyers, invoices, bank_acc, fy, protected_due_invoice_ids
    )

    print("  Creating supplier payments...")
    _seed_supplier_payments(db, admin.id, company.id, purchase_invoices, bank_acc, fy)

    print("  Creating credit / debit notes...")
    _seed_credit_notes(
        db, admin.id, company, invoices, purchase_invoices, fy, protected_due_invoice_ids
    )

    # Last, so invoice and credit-note stock movements don't overwrite it.
    _apply_stock_profile(db, company.id, products)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("Seeding demo data...")
        seed_all(db)
        print("Demo seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
