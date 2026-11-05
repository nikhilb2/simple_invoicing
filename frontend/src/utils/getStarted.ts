import type { DashboardMetrics } from '../types/api';

export type GetStartedStepId = 'customer' | 'product' | 'invoice' | 'bank';

export type GetStartedFacts = {
  /** Ledgers on the company. Null while unknown or if the lookup failed. */
  ledgerCount: number | null;
  /** Bank accounts. Null while unknown or if the lookup failed. */
  bankAccountCount: number | null;
};

export type GetStartedStatus = Record<GetStartedStepId, boolean>;

/** A company that has ever posted an invoice is past setup, whatever else is missing. */
export function hasPostedInvoices(metrics: Pick<DashboardMetrics, 'sales'>): boolean {
  return metrics.sales.sales_invoice_count + metrics.sales.purchase_invoice_count > 0;
}

export function getStartedStatus(metrics: DashboardMetrics, facts: GetStartedFacts): GetStartedStatus {
  const { catalog, inventory } = metrics;
  return {
    customer: (facts.ledgerCount ?? 0) > 0,
    // Stock only matters for products that track it: a services-only catalogue has
    // no tracked products and nothing to enter.
    product: catalog.total_products > 0 && (inventory.tracked_products === 0 || inventory.total_units > 0),
    invoice: hasPostedInvoices(metrics),
    bank: (facts.bankAccountCount ?? 0) > 0,
  };
}

/** The bank step is optional, so it never keeps the checklist on screen. */
export function isGetStartedComplete(status: GetStartedStatus): boolean {
  return status.customer && status.product && status.invoice;
}

/** Whether the checklist (and the lookups behind it) should run at all. */
export function shouldRunGetStarted(metrics: DashboardMetrics | null, dismissed: boolean): boolean {
  return metrics !== null && !dismissed && !hasPostedInvoices(metrics);
}

function dismissKey(companyId: string | null): string {
  return `get_started_dismissed_${companyId ?? 'none'}`;
}

/** localStorage can be missing or throw (privacy modes); the card is not worth breaking the dashboard. */
export function readGetStartedDismissed(companyId: string | null): boolean {
  try {
    return localStorage.getItem(dismissKey(companyId)) === 'true';
  } catch {
    return false;
  }
}

export function writeGetStartedDismissed(companyId: string | null): void {
  try {
    localStorage.setItem(dismissKey(companyId), 'true');
  } catch {
    /* ignore */
  }
}

export function activeCompanyId(): string | null {
  try {
    return localStorage.getItem('active_company_id');
  } catch {
    return null;
  }
}
