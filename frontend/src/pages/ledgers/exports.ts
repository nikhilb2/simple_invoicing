/**
 * Ledgers list CSV export.
 *
 * The ledgers list is paginated server side, so exporting only the rows on
 * screen would silently drop every ledger past the current page. This module
 * instead pages the list endpoint at its 500 row maximum with the same search
 * and sort the page applies, until the server's total_pages is reached, and
 * downloads every matching ledger. Quoting, the formula guard, and the UTF-8
 * BOM are owned by the shared helper in utils/csv.ts, so this module only
 * maps ledgers to rows and owns the paging.
 */
import api from '../../api/client';
import type { Ledger, PaginatedLedgers } from '../../types/api';
import { downloadCsv, toCsv, type CsvValue } from '../../utils/csv';

/** Columns of the export, in order. */
export const LEDGERS_CSV_HEADERS = ['Name', 'GSTIN', 'Phone', 'Email', 'Balance'];

/** The list endpoint's maximum page_size. */
const PAGE_SIZE = 500;

/**
 * One ledger as a CSV row, in header order. Balance stays a raw signed number
 * (positive debit, negative credit, as the page displays Dr/Cr) so the column
 * stays numeric in a spreadsheet; null email or balance exports as empty.
 */
export function ledgerToCsvRow(ledger: Ledger): CsvValue[] {
  return [ledger.name, ledger.gst, ledger.phone_number, ledger.email ?? '', ledger.balance ?? ''];
}

/** CSV text for a set of ledgers, headers included. */
export function buildLedgersCsv(ledgers: Ledger[]): string {
  return toCsv(
    LEDGERS_CSV_HEADERS,
    ledgers.map((ledger) => ledgerToCsvRow(ledger)),
  );
}

/**
 * Every ledger the current search and sort select, across all pages.
 *
 * A page that comes back empty while the server still claims more pages would
 * otherwise spin this loop forever, so an empty page ends the fetch.
 */
export async function fetchAllLedgers(search: string, sort: string): Promise<Ledger[]> {
  const ledgers: Ledger[] = [];
  let page = 1;
  let totalPages = 1;

  while (page <= totalPages) {
    const res = await api.get<PaginatedLedgers>('/ledgers/', {
      params: { page, page_size: PAGE_SIZE, search, sort },
    });
    totalPages = Math.max(1, res.data.total_pages);
    if (res.data.items.length === 0) break;
    ledgers.push(...res.data.items);
    page += 1;
  }

  return ledgers;
}

/** Fetches every matching ledger and downloads it as a CSV file. */
export async function exportLedgersCsv(search: string, sort: string): Promise<void> {
  const ledgers = await fetchAllLedgers(search, sort);
  downloadCsv(
    `ledgers_${new Date().toISOString().slice(0, 10)}.csv`,
    LEDGERS_CSV_HEADERS,
    ledgers.map((ledger) => ledgerToCsvRow(ledger)),
  );
}
