import type { CompanyProfile } from '../types/api';

export function isCompanyConfigured(company: CompanyProfile | null | undefined): boolean {
  return Boolean(company?.name?.trim());
}

/**
 * Mirrors the rule in the company routes: a company set up before GSTIN became
 * mandatory may keep saving without one, and everything else needs it.
 */
export function isGstinRequired(company: CompanyProfile | null | undefined): boolean {
  return !(company?.name?.trim() && company?.address?.trim()) || Boolean(company?.gst?.trim());
}
