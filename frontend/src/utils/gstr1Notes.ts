/**
 * What the file does with sales at 0%, which the data can't sort into nil-rated,
 * exempt, non-GST or zero-rated. Null when the period has none.
 */
export function zeroRateSalesNote(invoices: number, formattedValue: string): string | null {
  if (invoices <= 0) return null;
  return (
    `${invoices} ${invoices === 1 ? 'invoice has' : 'invoices have'} ${formattedValue} of sales at 0%. `
    + 'They count in the B2B, B2CL and B2CS figures, and the JSON files them there as taxable rows at rate 0, '
    + 'not in Table 8. If any are nil-rated, exempt, non-GST or zero-rated, check with your accountant and '
    + 'correct them on the portal.'
  );
}
