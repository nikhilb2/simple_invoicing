import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToString } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { GetStartedCard } from '../components/GetStartedChecklist';
import type { DashboardMetrics } from '../types/api';
import {
  getStartedStatus,
  isGetStartedComplete,
  readGetStartedDismissed,
  shouldRunGetStarted,
  writeGetStartedDismissed,
} from './getStarted';

function metrics(over: { products?: number; tracked?: number; units?: number; sales?: number; purchases?: number } = {}) {
  return {
    catalog: { total_products: over.products ?? 0, producible_products: 0 },
    inventory: { tracked_products: over.tracked ?? 0, total_units: over.units ?? 0 },
    sales: { sales_invoice_count: over.sales ?? 0, purchase_invoice_count: over.purchases ?? 0 },
  } as DashboardMetrics;
}

const none = { ledgerCount: 0, bankAccountCount: 0 };

describe('getStartedStatus', () => {
  it('starts with nothing done for a new company', () => {
    expect(getStartedStatus(metrics(), none)).toEqual({ customer: false, product: false, invoice: false, bank: false });
  });

  it('ticks the customer and bank steps from the lookups', () => {
    const status = getStartedStatus(metrics(), { ledgerCount: 2, bankAccountCount: 1 });
    expect(status.customer).toBe(true);
    expect(status.bank).toBe(true);
  });

  it('leaves steps unticked when a lookup failed', () => {
    const status = getStartedStatus(metrics(), { ledgerCount: null, bankAccountCount: null });
    expect(status.customer).toBe(false);
    expect(status.bank).toBe(false);
  });

  it('needs stock on a tracked product, but not for an untracked catalogue', () => {
    expect(getStartedStatus(metrics({ products: 1, tracked: 1, units: 0 }), none).product).toBe(false);
    expect(getStartedStatus(metrics({ products: 1, tracked: 1, units: 10 }), none).product).toBe(true);
    expect(getStartedStatus(metrics({ products: 1, tracked: 0 }), none).product).toBe(true);
  });

  it('counts a sales or purchase invoice as the invoice step', () => {
    expect(getStartedStatus(metrics({ sales: 1 }), none).invoice).toBe(true);
    expect(getStartedStatus(metrics({ purchases: 1 }), none).invoice).toBe(true);
  });

  it('treats the bank step as optional', () => {
    expect(isGetStartedComplete({ customer: true, product: true, invoice: true, bank: false })).toBe(true);
    expect(isGetStartedComplete({ customer: true, product: true, invoice: false, bank: true })).toBe(false);
  });
});

describe('shouldRunGetStarted', () => {
  it('waits for metrics', () => {
    expect(shouldRunGetStarted(null, false)).toBe(false);
  });
  it('runs for a company with no invoices', () => {
    expect(shouldRunGetStarted(metrics(), false)).toBe(true);
  });
  it('never runs for a company with invoices', () => {
    expect(shouldRunGetStarted(metrics({ sales: 3 }), false)).toBe(false);
  });
  it('stops once dismissed', () => {
    expect(shouldRunGetStarted(metrics(), true)).toBe(false);
  });
});

describe('dismissal storage', () => {
  afterEach(() => vi.unstubAllGlobals());

  function fakeStorage() {
    const store = new Map<string, string>();
    return {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    };
  }

  it('is remembered per company', () => {
    vi.stubGlobal('localStorage', fakeStorage());
    writeGetStartedDismissed('1');
    expect(readGetStartedDismissed('1')).toBe(true);
    expect(readGetStartedDismissed('2')).toBe(false);
  });

  it('tolerates storage being unavailable', () => {
    const broken = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    vi.stubGlobal('localStorage', broken);
    expect(() => writeGetStartedDismissed('1')).not.toThrow();
    expect(readGetStartedDismissed('1')).toBe(false);
  });
});

describe('GetStartedCard', () => {
  const render = (status: Parameters<typeof GetStartedCard>[0]['status']) =>
    renderToString(
      <MemoryRouter>
        <GetStartedCard status={status} onDismiss={() => {}} />
      </MemoryRouter>,
    );

  it('lists the steps, marks bank optional and links the Quick start', () => {
    const html = render({ customer: false, product: false, invoice: false, bank: false });
    expect(html).toContain('Add a customer');
    expect(html).toContain('Add a product with opening stock');
    expect(html).toContain('Create your first invoice');
    expect(html).toContain('(optional)');
    expect(html).toContain('href="/cash-bank/accounts"');
    expect(html).toContain('https://guide.simpleinvoicings.com/getting-started/');
  });

  it('shows finished steps as done without an action link', () => {
    const html = render({ customer: true, product: false, invoice: false, bank: false });
    expect(html).not.toContain('href="/ledgers/new"');
    expect(html).toContain('Done');
  });

  it('renders nothing once every required step is done', () => {
    expect(render({ customer: true, product: true, invoice: true, bank: false })).toBe('');
  });
});
