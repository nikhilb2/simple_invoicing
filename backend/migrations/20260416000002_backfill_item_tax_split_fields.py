"""
Backfill item-level GST split fields for existing invoices
"""

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_interstate_supply(company_gst: str | None, ledger_gst: str | None) -> bool:
    if not company_gst or not ledger_gst or len(company_gst) < 2 or len(ledger_gst) < 2:
        return False
    return company_gst[:2] != ledger_gst[:2]


def up(conn) -> None:
    invoice_rows = conn.execute(text("""
        SELECT id, company_gst, ledger_gst, cgst_amount, sgst_amount, igst_amount
        FROM invoices
        WHERE id IN (SELECT DISTINCT invoice_id FROM invoice_items)
        ORDER BY id
    """)).mappings().all()

    update_stmt = text("""
        UPDATE invoice_items
        SET cgst_amount = :cgst_amount,
            sgst_amount = :sgst_amount,
            igst_amount = :igst_amount
        WHERE id = :item_id
    """)

    for invoice in invoice_rows:
        item_rows = conn.execute(
            text("""
                SELECT id, tax_amount
                FROM invoice_items
                WHERE invoice_id = :invoice_id
                ORDER BY id
            """),
            {"invoice_id": invoice["id"]},
        ).mappings().all()

        if not item_rows:
            continue

        interstate_supply = _is_interstate_supply(invoice["company_gst"], invoice["ledger_gst"])
        item_tax_amounts = [_money(Decimal(str(item["tax_amount"] or 0))) for item in item_rows]
        total_item_tax = _money(sum(item_tax_amounts, Decimal("0")))

        if interstate_supply:
            remaining_igst = _money(Decimal(str(invoice["igst_amount"] or 0)))
            if remaining_igst == Decimal("0.00") and total_item_tax > 0:
                remaining_igst = total_item_tax

            for index, item in enumerate(item_rows):
                item_igst_amount = remaining_igst if index == len(item_rows) - 1 else item_tax_amounts[index]
                if index != len(item_rows) - 1:
                    remaining_igst = _money(remaining_igst - item_igst_amount)

                conn.execute(
                    update_stmt,
                    {
                        "item_id": item["id"],
                        "cgst_amount": 0,
                        "sgst_amount": 0,
                        "igst_amount": float(item_igst_amount),
                    },
                )
            continue

        remaining_cgst = _money(Decimal(str(invoice["cgst_amount"] or 0)))
        remaining_sgst = _money(Decimal(str(invoice["sgst_amount"] or 0)))
        if remaining_cgst == Decimal("0.00") and remaining_sgst == Decimal("0.00") and total_item_tax > 0:
            adjusted_total_item_tax = total_item_tax
            if int(adjusted_total_item_tax * Decimal("100")) % 2 != 0:
                adjusted_total_item_tax = _money(adjusted_total_item_tax + Decimal("0.01"))
            remaining_cgst = _money(adjusted_total_item_tax / Decimal("2"))
            remaining_sgst = _money(adjusted_total_item_tax / Decimal("2"))

        for index, item in enumerate(item_rows):
            item_tax_amount = item_tax_amounts[index]
            if index == len(item_rows) - 1:
                item_cgst_amount = remaining_cgst
                item_sgst_amount = remaining_sgst
            else:
                item_cgst_amount = _money(item_tax_amount / Decimal("2"))
                item_sgst_amount = _money(item_tax_amount - item_cgst_amount)
                remaining_cgst = _money(remaining_cgst - item_cgst_amount)
                remaining_sgst = _money(remaining_sgst - item_sgst_amount)

            conn.execute(
                update_stmt,
                {
                    "item_id": item["id"],
                    "cgst_amount": float(item_cgst_amount),
                    "sgst_amount": float(item_sgst_amount),
                    "igst_amount": 0,
                },
            )


def down(conn) -> None:
    conn.execute(text("""
        UPDATE invoice_items
        SET cgst_amount = 0,
            sgst_amount = 0,
            igst_amount = 0
    """))