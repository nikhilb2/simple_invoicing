import api from '../api/client';
import type { CompanyProfile, CompanyTermOut } from '../types/api';

export type CompanyProfileWithTerms = CompanyProfile;

export interface LogoUploadPayload {
  data: string;
  mime_type: string;
}

export interface TermCreatePayload {
  content: string;
}

export interface TermUpdatePayload {
  content: string;
}

export function getLogoUrl(company: CompanyProfileWithTerms): string | null {
  if (company.logo_data && company.logo_mime_type) {
    return `data:${company.logo_mime_type};base64,${company.logo_data}`;
  }
  return null;
}

export async function fetchCompany(): Promise<CompanyProfileWithTerms> {
  const res = await api.get<CompanyProfileWithTerms>('/company/');
  return res.data;
}

export async function updateCompany(payload: Partial<CompanyProfileWithTerms>): Promise<CompanyProfileWithTerms> {
  const res = await api.put<CompanyProfileWithTerms>('/company/', payload);
  return res.data;
}

export async function uploadLogo(payload: LogoUploadPayload): Promise<CompanyProfileWithTerms> {
  const res = await api.put<CompanyProfileWithTerms>('/company/logo', payload);
  return res.data;
}

export async function removeLogo(): Promise<CompanyProfileWithTerms> {
  const res = await api.delete<CompanyProfileWithTerms>('/company/logo');
  return res.data;
}

export async function listTerms(): Promise<CompanyTermOut[]> {
  const res = await api.get<CompanyTermOut[]>('/company/terms');
  return res.data;
}

export async function createTerm(payload: TermCreatePayload): Promise<CompanyTermOut> {
  const res = await api.post<CompanyTermOut>('/company/terms', payload);
  return res.data;
}

export async function updateTerm(termId: number, payload: TermUpdatePayload): Promise<CompanyTermOut> {
  const res = await api.put<CompanyTermOut>(`/company/terms/${termId}`, payload);
  return res.data;
}

export async function deleteTerm(termId: number): Promise<CompanyTermOut[]> {
  const res = await api.delete<CompanyTermOut[]>(`/company/terms/${termId}`);
  return res.data;
}
