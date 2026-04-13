import type { CompanyProfile } from '../types/api';

export function isCompanyConfigured(company: CompanyProfile | null | undefined): boolean {
  return Boolean(company?.name?.trim());
}
