/** Preview arithmetic follows InvoiceProcessor and document_totals on the server. */
export type InvoiceTotalLine = {
  unitPrice: number;
  quantity: number;
  gstRate: number;
  discountType?: string;
  discountValue?: number;
};

type Discount = { type?: string; value?: number };

/** ROUND_HALF_UP, including negative values; tolerate binary error at a tie. */
export function roundMoney(value: number): number {
  const magnitude = Math.abs(value);
  const rounded = Math.round((magnitude + 4 * Number.EPSILON * Math.max(1, magnitude)) * 100) / 100;
  return rounded === 0 ? 0 : Math.sign(value) * rounded;
}

function discountAmount(total: number, { type, value }: Discount): number {
  if (!type || value == null || !Number.isFinite(value) || value <= 0) return 0;
  return type === 'percentage' ? roundMoney(total * value / 100) : roundMoney(value);
}

export function computeLineTotal({
  unitPrice, quantity, gstRate, taxInclusive, discountType, discountValue, interstateSupply = true,
}: InvoiceTotalLine & { taxInclusive: boolean; interstateSupply?: boolean }) {
  if (![unitPrice, quantity, gstRate].every(Number.isFinite)) {
    return { taxableAmount: 0, taxAmount: 0, lineTotal: 0 };
  }
  let lineTotal = roundMoney(unitPrice * quantity);
  let taxableAmount = taxInclusive ? roundMoney(lineTotal / (1 + gstRate / 100)) : lineTotal;
  let taxAmount = taxInclusive
    ? roundMoney(lineTotal - taxableAmount)
    : roundMoney(taxableAmount * gstRate / 100);
  if (!taxInclusive) lineTotal = roundMoney(taxableAmount + taxAmount);

  const discount = discountAmount(taxableAmount, { type: discountType, value: discountValue });
  const appliedDiscount = discountType === 'percentage' ? discount : Math.min(discount, taxableAmount);
  if (appliedDiscount > 0) {
    taxableAmount = roundMoney(taxableAmount - appliedDiscount);
    if (taxInclusive) {
      lineTotal = roundMoney(taxableAmount * (1 + gstRate / 100));
      taxAmount = roundMoney(lineTotal - taxableAmount);
    } else {
      taxAmount = roundMoney(taxableAmount * gstRate / 100);
      lineTotal = roundMoney(taxableAmount + taxAmount);
    }
  }
  if (!interstateSupply) {
    // assign_item_tax_split rounds CGST and SGST separately at half the rate,
    // then replaces the preliminary tax and line total, even for inclusive prices.
    taxAmount = roundMoney(2 * roundMoney(taxableAmount * (gstRate / 2) / 100));
    lineTotal = roundMoney(taxableAmount + taxAmount);
  }
  return { taxableAmount, taxAmount, lineTotal };
}

export function computeInvoiceTotals(lines: InvoiceTotalLine[], {
  taxInclusive,
  invoiceDiscount = {},
  applyRoundOff = false,
  interstateSupply = true,
}: {
  taxInclusive: boolean; invoiceDiscount?: Discount; applyRoundOff?: boolean; interstateSupply?: boolean;
}) {
  const calculated = lines.map((line) => computeLineTotal({ ...line, taxInclusive, interstateSupply }));
  const taxableAmount = roundMoney(calculated.reduce((sum, line) => sum + line.taxableAmount, 0));
  const taxAmount = roundMoney(calculated.reduce((sum, line) => sum + line.taxAmount, 0));
  const totalAmount = roundMoney(taxableAmount + taxAmount);
  const invoiceDiscountAmount = Math.min(discountAmount(totalAmount, invoiceDiscount), totalAmount);
  const afterDiscountTotal = roundMoney(totalAmount - invoiceDiscountAmount);
  const total = applyRoundOff
    ? Math.sign(afterDiscountTotal) * Math.round(Math.abs(afterDiscountTotal))
    : afterDiscountTotal;
  return {
    taxableAmount, taxAmount, totalAmount, invoiceDiscountAmount, afterDiscountTotal,
    roundOffAmount: roundMoney(total - afterDiscountTotal), total,
  };
}
