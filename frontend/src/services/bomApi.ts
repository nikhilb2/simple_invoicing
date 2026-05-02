import api, { getApiErrorMessage } from '../api/client';
import type {
  BOMComponent,
  BOMCreate,
  BOMUpdate,
  ProduceRequest,
  ProduceResponse,
  ProductionTransaction,
  PaginatedProductionTransactions,
} from '../types/api';

export async function fetchBOM(productId: number): Promise<BOMComponent[]> {
  const res = await api.get<BOMComponent[]>(`/bom/product/${productId}`);
  return res.data;
}

export async function createBOMEntry(payload: BOMCreate): Promise<{ id: number; message: string }> {
  const res = await api.post<{ id: number; message: string }>('/bom/', payload);
  return res.data;
}

export async function updateBOMEntry(bomId: number, payload: BOMUpdate): Promise<{ id: number; message: string }> {
  const res = await api.put<{ id: number; message: string }>(`/bom/${bomId}`, payload);
  return res.data;
}

export async function deleteBOMEntry(bomId: number): Promise<{ message: string; product_id: number }> {
  const res = await api.delete<{ message: string; product_id: number }>(`/bom/${bomId}`);
  return res.data;
}

export async function produceBatch(payload: ProduceRequest): Promise<ProduceResponse> {
  const res = await api.post<ProduceResponse>('/inventory/produce', payload);
  return res.data;
}

export async function fetchProductionHistory(
  page: number = 1,
  pageSize: number = 20
): Promise<PaginatedProductionTransactions> {
  const res = await api.get<PaginatedProductionTransactions>('/inventory/production-history', {
    params: { page, page_size: pageSize },
  });
  return res.data;
}
