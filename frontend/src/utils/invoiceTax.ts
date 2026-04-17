import formatCurrency from './formatting';

type InvoiceTaxBreakdownArgs = {
  gstRate: number;
  taxAmount: number;
  currencyCode: string;
  cgstAmount?: number | null;
  sgstAmount?: number | null;
  igstAmount?: number | null;
  interstateSupply?: boolean;
};

function roundCurrency(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function formatRate(rate: number): string {
  return rate.toFixed(2).replace(/\.00$/, '').replace(/(\.\d*[1-9])0+$/, '$1');
}

export function isInterstateSupply(companyGst?: string | null, ledgerGst?: string | null): boolean {
  const normalizedCompanyGst = companyGst?.trim() || '';
  const normalizedLedgerGst = ledgerGst?.trim() || '';

  if (normalizedCompanyGst.length < 2 || normalizedLedgerGst.length < 2) {
    return false;
  }

  return normalizedCompanyGst.slice(0, 2) !== normalizedLedgerGst.slice(0, 2);
}

export function formatInvoiceTaxBreakdown({
  gstRate,
  taxAmount,
  currencyCode,
  cgstAmount,
  sgstAmount,
  igstAmount,
  interstateSupply,
}: InvoiceTaxBreakdownArgs): string {
  const normalizedGstRate = Number.isFinite(gstRate) ? gstRate : 0;
  const normalizedTaxAmount = roundCurrency(Number.isFinite(taxAmount) ? taxAmount : 0);
  const normalizedIgstAmount = roundCurrency(Number.isFinite(igstAmount ?? NaN) ? Number(igstAmount) : 0);
  const normalizedCgstAmount = roundCurrency(Number.isFinite(cgstAmount ?? NaN) ? Number(cgstAmount) : 0);
  const normalizedSgstAmount = roundCurrency(Number.isFinite(sgstAmount ?? NaN) ? Number(sgstAmount) : 0);

  if (normalizedIgstAmount > 0) {
    return `IGST ${formatRate(normalizedGstRate)}% (${formatCurrency(normalizedIgstAmount, currencyCode)})`;
  }

  if (normalizedCgstAmount > 0 || normalizedSgstAmount > 0) {
    return `CGST ${formatRate(normalizedGstRate / 2)}% (${formatCurrency(normalizedCgstAmount, currencyCode)}) + SGST ${formatRate(normalizedGstRate / 2)}% (${formatCurrency(normalizedSgstAmount, currencyCode)})`;
  }

  if (normalizedTaxAmount <= 0) {
    return `GST ${formatRate(normalizedGstRate)}% (${formatCurrency(0, currencyCode)})`;
  }

  if (interstateSupply) {
    return `IGST ${formatRate(normalizedGstRate)}% (${formatCurrency(normalizedTaxAmount, currencyCode)})`;
  }

  const splitCgstAmount = roundCurrency(normalizedTaxAmount / 2);
  const splitSgstAmount = splitCgstAmount;
  return `CGST ${formatRate(normalizedGstRate / 2)}% (${formatCurrency(splitCgstAmount, currencyCode)}) + SGST ${formatRate(normalizedGstRate / 2)}% (${formatCurrency(splitSgstAmount, currencyCode)})`;
}