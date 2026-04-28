import type { Invoice } from '../types/api';

export type InvoiceCreditStatusMeta = {
  label: string;
  background: string;
  color: string;
};

export const invoiceCreditStatusMeta: Record<Invoice['credit_status'], InvoiceCreditStatusMeta> = {
  not_credited: { label: 'Not credited', background: '#e0f2fe', color: '#075985' },
  partially_credited: { label: 'Partially credited', background: '#fef3c7', color: '#92400e' },
  fully_credited: { label: 'Fully credited', background: '#dcfce7', color: '#166534' },
};
