import type {
  InvoiceCreate,
  InvoiceItemInput,
  Quotation,
  QuotationConversionDraft,
  QuotationConvert,
  QuotationDocumentType,
  QuotationFields,
} from '../types/api';
import type { InvoiceFormItem } from '../pages/invoices/types';

/** Everything the composer's voucher select can hold. */
export type ComposerVoucherType = 'sales' | 'purchase' | 'payment' | 'receipt' | QuotationDocumentType;

export const DEFAULT_VALIDITY_DAYS = 30;

export function isQuotationVoucher(voucherType: ComposerVoucherType): voucherType is QuotationDocumentType {
  return voucherType === 'quotation' || voucherType === 'proforma';
}

/** The fields that only make sense when selling: reference notes, shipping. */
export function isSaleLikeVoucher(voucherType: ComposerVoucherType): boolean {
  return voucherType === 'sales' || isQuotationVoucher(voucherType);
}

/**
 * `date` plus a number of days, both as YYYY-MM-DD.
 *
 * Works on the calendar date in UTC on purpose: going through a local Date lands on
 * the previous day east of UTC, which is everywhere this app is used.
 */
export function addDaysToIsoDate(date: string, days: number): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) {
    return '';
  }
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

export function defaultValidUntil(date: string): string {
  return addDaysToIsoDate(date, DEFAULT_VALIDITY_DAYS);
}

/** What the composer calls the document it is building, for headings and buttons. */
export function composerDocumentName(voucherType: ComposerVoucherType): string {
  if (voucherType === 'quotation') return 'quotation';
  if (voucherType === 'proforma') return 'proforma invoice';
  return 'invoice';
}

/** A line as the form holds it. No serials: those are physical units, scanned at conversion. */
function toFormItem(
  line: Pick<InvoiceItemInput, 'product_id' | 'quantity' | 'unit_price' | 'description' | 'discount_type' | 'discount_value'>,
  index: number,
): InvoiceFormItem {
  return {
    id: index + 1,
    productId: String(line.product_id),
    quantity: String(line.quantity),
    unit_price: line.unit_price != null ? String(line.unit_price) : '',
    description: line.description ?? '',
    discount_type: line.discount_type ?? '',
    discount_value: line.discount_value != null ? String(line.discount_value) : '',
    serials: [],
    autoFilled: false,
  };
}

export function quotationToFormItems(quotation: Pick<Quotation, 'items'>): InvoiceFormItem[] {
  return quotation.items.map((line, index) =>
    toFormItem(
      {
        product_id: line.product_id,
        quantity: line.quantity,
        unit_price: line.unit_price,
        description: line.description ?? undefined,
        discount_type: (line.discount_type as 'percentage' | 'net' | null) ?? null,
        discount_value: line.discount_value ?? null,
      },
      index,
    ),
  );
}

export function conversionDraftToFormItems(invoice: Pick<InvoiceCreate, 'items'>): InvoiceFormItem[] {
  return invoice.items.map(toFormItem);
}

/**
 * The form as saved, stamped with the version of the quotation the draft came from.
 * The stamp is passed along untouched: the server compares it to the microsecond, and
 * going through a JavaScript Date would drop the last three digits.
 */
export function conversionPayload(payload: InvoiceCreate, draft: Pick<QuotationConversionDraft, 'invoice'>): QuotationConvert {
  return { ...payload, quotation_updated_at: draft.invoice.quotation_updated_at };
}

/**
 * Products this invoice carries fewer of than the quotation did.
 *
 * Reducing a line is allowed, but conversion is full only: the document closes and the
 * difference is not left open, so the composer says so while it can still be changed.
 * Worth saying most for a serial-tracked line, whose quantity is whatever has been
 * scanned so far rather than a number anyone chose.
 */
export function conversionLineShortfalls(
  quoted: Pick<InvoiceItemInput, 'product_id' | 'quantity'>[],
  onInvoice: { productId: number; quantity: number }[],
): { productId: number; quoted: number; onInvoice: number }[] {
  const totals = new Map<number, number>();
  for (const line of quoted) {
    totals.set(line.product_id, (totals.get(line.product_id) ?? 0) + line.quantity);
  }
  const shortfalls: { productId: number; quoted: number; onInvoice: number }[] = [];
  for (const [productId, wanted] of totals) {
    const actual = onInvoice
      .filter((line) => line.productId === productId)
      .reduce((sum, line) => sum + (Number.isNaN(line.quantity) ? 0 : line.quantity), 0);
    if (actual < wanted) {
      shortfalls.push({ productId, quoted: wanted, onInvoice: actual });
    }
  }
  return shortfalls;
}

/** A form line as a quotation line, with no serials and no tax override. */
export function formItemToQuotationLine(item: InvoiceFormItem): QuotationFields['items'][number] {
  return {
    product_id: Number(item.productId),
    quantity: Number(item.quantity),
    unit_price: item.unit_price ? Number(item.unit_price) : undefined,
    description: item.description || undefined,
    discount_type: item.discount_type || null,
    discount_value: item.discount_value ? Number(item.discount_value) : null,
  };
}
