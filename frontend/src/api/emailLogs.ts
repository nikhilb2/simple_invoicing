import api from './client';

export interface EmailLog {
  id: number;
  company_id: number | null;
  to_email: string;
  cc: string | null;
  subject: string;
  email_type: string;
  reference_id: number | null;
  status: 'sent' | 'failed';
  error_message: string | null;
  sent_by_user_id: number | null;
  sent_at: string;
}

export interface PaginatedEmailLogs {
  items: EmailLog[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface EmailLogFilters {
  page?: number;
  page_size?: number;
  email_type?: string;
  status?: string;
  from_date?: string;
  to_date?: string;
}

export async function listEmailLogs(filters: EmailLogFilters = {}): Promise<PaginatedEmailLogs> {
  const params: Record<string, string | number> = {};
  if (filters.page) params.page = filters.page;
  if (filters.page_size) params.page_size = filters.page_size;
  if (filters.email_type) params.email_type = filters.email_type;
  if (filters.status) params.status = filters.status;
  if (filters.from_date) params.from_date = filters.from_date;
  if (filters.to_date) params.to_date = filters.to_date;

  const res = await api.get<PaginatedEmailLogs>('/email-logs/', { params });
  return res.data;
}
