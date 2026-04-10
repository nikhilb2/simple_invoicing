import api from './client';

export interface FinancialYear {
  id: number;
  label: string;
  start_date: string;
  end_date: string;
  is_active: boolean;
  created_at?: string | null;
}

export async function getFinancialYears(): Promise<FinancialYear[]> {
  const res = await api.get<FinancialYear[]>('/financial-years/');
  return res.data;
}

export async function createFinancialYear(data: {
  label: string;
  start_date: string;
  end_date: string;
}): Promise<FinancialYear> {
  const res = await api.post<FinancialYear>('/financial-years/', data);
  return res.data;
}

export async function activateFinancialYear(id: number): Promise<FinancialYear> {
  const res = await api.put<FinancialYear>(`/financial-years/${id}/activate`);
  return res.data;
}
