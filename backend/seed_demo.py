"""Seed demo data for the invoicing application.

Deletes ALL existing transactional data (company profile, bank accounts, buyers,
products, inventory, invoices, credit notes, payments) and recreates:

  * 1 company profile
  * 1 bank account + 1 cash account
  * 10 buyers / ledgers
  * 25 products with 500 units of inventory each
    * 100 sales invoices + 40 purchase invoices with 2-5 line items each
  * 50 payment receipts with invoice allocations

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
from src.services.series import generate_next_number

random.seed(42)

TARGET_FY_LABEL = "2026-27"
TARGET_FY_START = date(2026, 4, 1)
TARGET_FY_END = date(2027, 3, 31)
SALES_INVOICE_COUNT = 100
PURCHASE_INVOICE_COUNT = 40

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
    dict(sku="LAPTOP-01",   name='Business Laptop 15"',       description="Intel Core i7, 16 GB RAM, 512 GB SSD",   hsn_sac="84713010", price=65000.00, gst_rate=18),
    dict(sku="LAPTOP-02",   name='Ultrabook 13"',              description="Ryzen 7, 16 GB RAM, 1 TB NVMe",          hsn_sac="84713010", price=72000.00, gst_rate=18),
    dict(sku="MONITOR-01",  name='27" 4K Monitor',             description="IPS, 144 Hz, USB-C",                     hsn_sac="84713040", price=28000.00, gst_rate=18),
    dict(sku="MONITOR-02",  name='24" FHD Monitor',            description="IPS, 75 Hz, HDMI+DP",                    hsn_sac="84713040", price=14500.00, gst_rate=18),
    dict(sku="KEYBOARD-01", name="Mechanical Keyboard",        description="Cherry MX Red switches, TKL layout",     hsn_sac="84716060", price=4500.00,  gst_rate=18),
    dict(sku="MOUSE-01",    name="Wireless Mouse",             description="2.4 GHz, 4000 DPI, ergonomic",           hsn_sac="84716060", price=1800.00,  gst_rate=18),
    dict(sku="HEADSET-01",  name="Over-ear Headset",           description="Noise-cancelling, USB, mic included",    hsn_sac="85183000", price=5500.00,  gst_rate=18),
    dict(sku="WEBCAM-01",   name="Full HD Webcam",             description="1080p, built-in mic, USB",               hsn_sac="85258020", price=3200.00,  gst_rate=18),
    dict(sku="HDD-01",      name="1 TB External HDD",          description="USB 3.0, portable",                      hsn_sac="84717010", price=4200.00,  gst_rate=18),
    dict(sku="SSD-01",      name="512 GB SSD",                 description="SATA III, 2.5 inch",                     hsn_sac="84717010", price=5800.00,  gst_rate=12),
    dict(sku="RAM-01",      name="16 GB DDR4 RAM",             description="3200 MHz, single stick",                 hsn_sac="84717010", price=3500.00,  gst_rate=12),
    dict(sku="ROUTER-01",   name="Wi-Fi 6 Router",             description="Dual-band, AX3000",                      hsn_sac="85176200", price=6800.00,  gst_rate=18),
    dict(sku="SWITCH-01",   name="8-Port Network Switch",      description="Gigabit, unmanaged",                     hsn_sac="85176200", price=2400.00,  gst_rate=18),
    dict(sku="HDMI-01",     name="HDMI 2.0 Cable 2m",          description="4K@60Hz, gold-plated connectors",        hsn_sac="85444290", price=450.00,   gst_rate=18),
    dict(sku="USBC-01",     name="USB-C Cable 1m",             description="100W PD, Gen 2",                         hsn_sac="85444290", price=650.00,   gst_rate=18),
    dict(sku="CHARGER-01",  name="65W GaN Charger",            description="USB-C, 3-port",                          hsn_sac="85044030", price=2200.00,  gst_rate=18),
    dict(sku="BAG-01",      name='15" Laptop Bag',             description="Water-resistant, multiple compartments", hsn_sac="42021200", price=1200.00,  gst_rate=12),
    dict(sku="STAND-01",    name="Adjustable Laptop Stand",    description="Aluminium, 6 heights",                   hsn_sac="94039000", price=2800.00,  gst_rate=18),
    dict(sku="DOCK-01",     name="USB-C Docking Station",      description="10-in-1, 4K60Hz dual display",           hsn_sac="84733020", price=8500.00,  gst_rate=18),
    dict(sku="UPS-01",      name="600 VA UPS",                 description="Line-interactive, 10 min backup",        hsn_sac="85044040", price=4600.00,  gst_rate=18),
    dict(sku="PRINTER-01",  name="Laser Printer A4",           description="Mono, 30 ppm, network",                  hsn_sac="84433200", price=18000.00, gst_rate=18),
    dict(sku="TONER-01",    name="Laser Toner Cartridge",      description="Compatible, 5000 pages",                 hsn_sac="84439980", price=1800.00,  gst_rate=18),
    dict(sku="PAPER-01",    name="A4 Copier Paper (500 sheets)", description="80 gsm, bright white",                 hsn_sac="48025590", price=320.00,   gst_rate=12),
    dict(sku="AV-01",       name="Antivirus 1-Year License",   description="3 devices, cloud backup included",       hsn_sac="99831190", price=1200.00,  gst_rate=18),
    dict(sku="AMC-01",      name="Annual Maintenance Contract", description="On-site support, 4-hr SLA",             hsn_sac="99831190", price=12000.00, gst_rate=18),
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


def _ensure_target_financial_year(db) -> FinancialYear:
    """Create/activate FY 2026-27 and return it."""
    fy = db.query(FinancialYear).filter(FinancialYear.label == TARGET_FY_LABEL).first()
    if fy is None:
        fy = FinancialYear(
            label=TARGET_FY_LABEL,
            start_date=TARGET_FY_START,
            end_date=TARGET_FY_END,
            is_active=True,
        )
        db.add(fy)
    else:
        fy.start_date = TARGET_FY_START
        fy.end_date = TARGET_FY_END
        fy.is_active = True

    db.query(FinancialYear).filter(FinancialYear.label != TARGET_FY_LABEL).update(
        {"is_active": False},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(fy)
    return fy


def _ensure_series_for_financial_year(db, fy: FinancialYear) -> None:
    """Ensure FY-scoped numbering series exists for sales and payment vouchers."""
    defaults = {
        "sales": "INV",
        "purchase": "PINV",
        "payment": "PAY",
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

def _delete_demo_data(db) -> None:
    print("  Deleting existing data...")
    db.query(PaymentInvoiceAllocation).delete(synchronize_session=False)
    db.query(Payment).delete(synchronize_session=False)
    db.query(CreditNoteItem).delete(synchronize_session=False)
    db.query(CreditNoteInvoiceRef).delete(synchronize_session=False)
    db.query(CreditNote).delete(synchronize_session=False)
    db.query(InvoiceItem).delete(synchronize_session=False)
    db.query(Invoice).delete(synchronize_session=False)
    db.query(Inventory).delete(synchronize_session=False)
    db.query(Product).delete(synchronize_session=False)
    db.query(CompanyAccount).delete(synchronize_session=False)
    db.query(Buyer).delete(synchronize_session=False)
    db.query(CompanyProfile).delete(synchronize_session=False)
    db.commit()
    # Reset series counters so demo numbering starts at INV-YYYY-001 / PAY-YYYY-001
    db.query(InvoiceSeries).update({"next_sequence": 1}, synchronize_session=False)
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


def _seed_accounts(db, admin_id: int) -> tuple:
    bank = CompanyAccount(
        account_type="bank",
        display_name="HDFC Current Account",
        bank_name="HDFC Bank",
        branch_name="Koramangala Branch",
        account_name="Respawn Technologies Pvt Ltd",
        account_number="50200012345678",
        ifsc_code="HDFC0001234",
        display_on_invoice=True,
        opening_balance=Decimal("500000.00"),
        is_active=True,
        created_by=admin_id,
    )
    cash = CompanyAccount(
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


def _seed_buyers(db) -> list:
    buyers = []
    for data in BUYERS:
        b = Buyer(**data)
        db.add(b)
        buyers.append(b)
    db.commit()
    for b in buyers:
        db.refresh(b)
    print(f"  Buyers: {len(buyers)}")
    return buyers


def _seed_products(db) -> list:
    """Create products and paired inventory rows (500 units each)."""
    products = []
    for data in PRODUCTS:
        p = Product(**data)
        db.add(p)
        db.flush()
        db.add(Inventory(product_id=p.id, quantity=500))
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
) -> tuple[list, set[int]]:
    fy_id = fy.id if fy else None
    today = date.today()
    invoices = []
    protected_due_invoice_ids: set[int] = set()

    # Keep invoice dates inside FY 2026-27.
    date_floor = fy.start_date if fy else TARGET_FY_START
    date_ceiling = min(today, fy.end_date) if fy else today

    if date_ceiling < date_floor:
        date_ceiling = date_floor

    for i in range(SALES_INVOICE_COUNT):
        # Spread invoices across FY 2026-27 up to today's date.
        spread_days = (date_ceiling - date_floor).days
        invoice_date = date_floor + timedelta(days=random.randint(0, max(spread_days, 0)))
        buyer = random.choice(buyers)
        selected = random.sample(products, random.randint(2, 5))
        interstate = _is_interstate(company.gst, buyer.gst)

        # Guarantee some overdue invoices with pending balances for the Due Invoices page.
        due_date = None
        if i < 45:
            overdue_days = random.randint(5, 45)
            due_base = today - timedelta(days=overdue_days)
            due_base = max(date_floor, min(due_base, date_ceiling))
            invoice_date = max(date_floor, due_base - timedelta(days=random.randint(5, 25)))
            due_date = due_base
        elif i < 75:
            lead_days = random.randint(7, 45)
            due_date = min(TARGET_FY_END, invoice_date + timedelta(days=lead_days))

        invoice = Invoice(
            total_amount=0,
            created_by=admin_id,
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
        invoice.invoice_number = generate_next_number(db, "sales", fy_id, invoice_date)

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
            inv = db.query(Inventory).filter(Inventory.product_id == product.id).first()
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

        if i < 20:
            protected_due_invoice_ids.add(invoice.id)

        if (i + 1) % 25 == 0:
            db.commit()
            print(f"    {i + 1}/{SALES_INVOICE_COUNT} sales invoices committed")

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
) -> list:
    fy_id = fy.id if fy else None
    today = date.today()
    invoices = []

    date_floor = fy.start_date if fy else TARGET_FY_START
    date_ceiling = min(today, fy.end_date) if fy else today
    if date_ceiling < date_floor:
        date_ceiling = date_floor

    for i in range(PURCHASE_INVOICE_COUNT):
        spread_days = (date_ceiling - date_floor).days
        invoice_date = date_floor + timedelta(days=random.randint(0, max(spread_days, 0)))
        vendor = random.choice(buyers)
        selected = random.sample(products, random.randint(2, 5))
        interstate = _is_interstate(company.gst, vendor.gst)

        due_date = min(TARGET_FY_END, invoice_date + timedelta(days=random.randint(15, 45)))

        invoice = Invoice(
            total_amount=0,
            created_by=admin_id,
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
            supplier_invoice_number=f"SUP-{TARGET_FY_LABEL}-{i + 1:04d}",
            tax_inclusive=False,
            apply_round_off=False,
            round_off_amount=0.0,
        )
        db.add(invoice)
        db.flush()

        invoice.invoice_number = generate_next_number(db, "purchase", fy_id, invoice_date)

        taxable_total = Decimal("0")
        items: list[InvoiceItem] = []

        for product in selected:
            qty = random.randint(5, 25)
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

            # Purchase vouchers restock inventory.
            inv = db.query(Inventory).filter(Inventory.product_id == product.id).first()
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
            print(f"    {i + 1}/{PURCHASE_INVOICE_COUNT} purchase invoices committed")

    db.commit()
    for inv in invoices:
        db.refresh(inv)
    return invoices


def _seed_receipts(
    db,
    admin_id: int,
    buyers: list,
    invoices: list,
    bank_acc: CompanyAccount,
    fy,
    excluded_invoice_ids: set[int],
) -> list:
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

    while len(receipts) < 50 and attempts < 150:
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
            alloc = _money(rem * Decimal(str(round(random.uniform(0.4, 1.0), 4))))
            alloc = min(alloc, rem)
            if alloc <= 0:
                continue
            total += alloc
            allocs.append((inv.id, alloc))
            remaining[inv.id] = _money(rem - alloc)

        if total <= 0 or not allocs:
            continue

        pmt_date = today - timedelta(days=random.randint(0, 90))
        payment = Payment(
            ledger_id=buyer.id,
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

        payment.payment_number = generate_next_number(db, "payment", fy_id, pmt_date)

        for inv_id, alloc_amount in allocs:
            db.add(PaymentInvoiceAllocation(
                payment_id=payment.id,
                invoice_id=inv_id,
                allocated_amount=float(alloc_amount),
            ))

        receipts.append(payment)

        if len(receipts) % 10 == 0:
            db.commit()
            print(f"    {len(receipts)}/50 receipts committed")

    db.commit()
    print(f"  Receipts: {len(receipts)}")
    return receipts


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def seed_all(db) -> None:
    admin = db.query(User).filter(User.email == "admin@simple.dev").first()
    if not admin:
        print("ERROR: Admin user not found. Run `python seed_admin.py` first.")
        sys.exit(1)

    fy = _ensure_target_financial_year(db)
    print(f"  Active financial year forced to: {fy.label} ({fy.start_date} to {fy.end_date})")

    _delete_demo_data(db)
    _ensure_series_for_financial_year(db, fy)

    company = _seed_company(db)
    bank_acc, _cash_acc = _seed_accounts(db, admin.id)
    buyers = _seed_buyers(db)
    products = _seed_products(db)

    print("  Creating invoices...")
    invoices, protected_due_invoice_ids = _seed_invoices(db, admin.id, company, buyers, products, fy)
    print(f"  Sales invoices: {len(invoices)}")

    print("  Creating purchase invoices...")
    purchase_invoices = _seed_purchase_invoices(db, admin.id, company, buyers, products, fy)
    print(f"  Purchase invoices: {len(purchase_invoices)}")

    print("  Creating receipts...")
    _seed_receipts(db, admin.id, buyers, invoices, bank_acc, fy, protected_due_invoice_ids)


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
