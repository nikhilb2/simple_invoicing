import api from '../../api/client';
import type { Gstr3bExportFormat, Gstr3bWorksheet } from './types';

const REPORT_TIMEOUT_MS = 60_000;

export async function fetchWorksheet(fromDate: string, toDate: string): Promise<Gstr3bWorksheet> {
  const response = await api.get<Gstr3bWorksheet>('/ledgers/tax-ledger/gstr3b/worksheet', {
    params: { from_date: fromDate, to_date: toDate },
    timeout: REPORT_TIMEOUT_MS,
  });
  return response.data;
}

export async function downloadWorksheet(
  format: Gstr3bExportFormat,
  fromDate: string,
  toDate: string,
): Promise<void> {
  const response = await api.get(`/ledgers/tax-ledger/gstr3b/export-${format}`, {
    params: { from_date: fromDate, to_date: toDate },
    responseType: 'blob',
    timeout: REPORT_TIMEOUT_MS,
  });
  const url = window.URL.createObjectURL(response.data as Blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `gstr3b_worksheet_${fromDate}_${toDate}.${format}`;
  link.click();
  window.URL.revokeObjectURL(url);
}
