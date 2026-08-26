import axios from 'axios';
import api, { getApiErrorMessage } from '../../api/client';
import type { PaginatedSerials, ScanResult, SerialStatus } from './types';

export type AvailableSerialFilters = {
  productId: number;
  search?: string;
  page?: number;
  pageSize?: number;
  /** Omit to get every unit except voided ones — what the warranty drawer wants. */
  status?: SerialStatus | null;
};

/**
 * The scan bar's only lookup. A code that matches nothing is a 404 carrying a
 * message written for the shopkeeper, so it is returned as `null` rather than
 * thrown — the caller prints the detail and carries on scanning. Everything
 * else (offline, 500, an expired token) is still a throw, because those are not
 * answers about the code.
 */
export type ScanLookup =
  | { found: true; result: ScanResult }
  | { found: false; detail: string };

export async function scanCode(code: string): Promise<ScanLookup> {
  try {
    const res = await api.get<ScanResult>('/serials/scan', { params: { code } });
    return { found: true, result: res.data };
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      return { found: false, detail: getApiErrorMessage(err, 'Not in stock — check the code, or receive it on a purchase entry first.') };
    }
    throw err;
  }
}

/**
 * Serials for one product, oldest first so FIFO is the default pick.
 *
 * Defaults to in-stock — the picker only ever offers sellable units. Pass
 * `status: null` for the full history a warranty lookup needs.
 */
export async function fetchAvailableSerials(filters: AvailableSerialFilters): Promise<PaginatedSerials> {
  const params: Record<string, string | number> = {
    product_id: filters.productId,
    page: filters.page ?? 1,
    page_size: filters.pageSize ?? 50,
  };

  const status = filters.status === undefined ? 'in_stock' : filters.status;
  if (status) {
    params.status = status;
  }

  if (filters.search?.trim()) {
    params.search = filters.search.trim();
  }

  const res = await api.get<PaginatedSerials>('/serials/', { params });
  return res.data;
}
