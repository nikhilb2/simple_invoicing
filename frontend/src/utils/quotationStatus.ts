import type { Quotation, QuotationDisplayStatus, QuotationDocumentType } from '../types/api';

/** The chips on the list, in the order someone working through them reads them. */
export const QUOTATION_STATUS_FILTERS: { value: QuotationDisplayStatus; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'expired', label: 'Expired' },
  { value: 'converted', label: 'Converted' },
  { value: 'declined', label: 'Declined' },
  { value: 'cancelled', label: 'Cancelled' },
];

export const QUOTATION_STATUS_LABELS: Record<QuotationDisplayStatus, string> = {
  open: 'Open',
  accepted: 'Accepted',
  expired: 'Expired',
  converted: 'Converted',
  declined: 'Declined',
  cancelled: 'Cancelled',
};

export const QUOTATION_DOCUMENT_LABELS: Record<QuotationDocumentType, string> = {
  quotation: 'Quotation',
  proforma: 'Proforma invoice',
};

/**
 * Whether the list can say there is nothing to show. A list that failed to load does
 * not know that, and telling someone with quotations that they have none is worse
 * than showing nothing beside the error.
 */
export function showQuotationsEmptyState(list: { isLoading: boolean; isError: boolean; rowCount: number }): boolean {
  return !list.isLoading && !list.isError && list.rowCount === 0;
}

/** The status chip colours the rest of the app already uses. */
export function quotationStatusBadgeClass(status: QuotationDisplayStatus): string {
  switch (status) {
    case 'accepted':
    case 'converted':
      return 'status-chip status-chip--success';
    case 'declined':
      return 'status-chip status-chip--rejected';
    case 'cancelled':
      return 'status-chip status-chip--cancelled';
    case 'expired':
      return 'status-chip status-chip--expired';
    default:
      return 'status-chip';
  }
}

export type QuotationAction =
  | 'edit'
  | 'accept'
  | 'decline'
  | 'reopen'
  | 'convert'
  | 'duplicate'
  | 'cancel'
  | 'share';

/**
 * Which actions a document offers, from its stored status.
 *
 * Mirrors the server's rules so a closed document shows no dead buttons; the server
 * still decides. Expiry changes nothing here: an expired quote can still be edited
 * (to extend it) or converted (with a warning), so this reads `status`, not
 * `display_status`.
 */
export function allowedQuotationActions(quotation: Pick<Quotation, 'status'>): QuotationAction[] {
  switch (quotation.status) {
    case 'open':
      return ['edit', 'convert', 'accept', 'decline', 'duplicate', 'share', 'cancel'];
    case 'accepted':
      return ['edit', 'convert', 'reopen', 'duplicate', 'share', 'cancel'];
    case 'declined':
      return ['reopen', 'duplicate', 'share', 'cancel'];
    case 'converted':
      return ['duplicate', 'share'];
    case 'cancelled':
      return ['duplicate'];
    default:
      return [];
  }
}
