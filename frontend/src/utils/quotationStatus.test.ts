import { describe, expect, it } from 'vitest';
import {
  QUOTATION_STATUS_FILTERS,
  allowedQuotationActions,
  quotationStatusBadgeClass,
  showQuotationsEmptyState,
} from './quotationStatus';

describe('showQuotationsEmptyState', () => {
  it('shows only once a load has succeeded with no rows', () => {
    expect(showQuotationsEmptyState({ isLoading: false, isError: false, rowCount: 0 })).toBe(true);
  });

  it('does not claim there are no quotations when the load failed', () => {
    expect(showQuotationsEmptyState({ isLoading: false, isError: true, rowCount: 0 })).toBe(false);
  });

  it('stays out of the way while loading or when there are rows', () => {
    expect(showQuotationsEmptyState({ isLoading: true, isError: false, rowCount: 0 })).toBe(false);
    expect(showQuotationsEmptyState({ isLoading: false, isError: false, rowCount: 2 })).toBe(false);
  });
});

describe('allowedQuotationActions', () => {
  it('offers everything on an open document', () => {
    expect(allowedQuotationActions({ status: 'open' })).toEqual([
      'edit', 'convert', 'accept', 'decline', 'duplicate', 'share', 'cancel',
    ]);
  });

  it('lets an accepted document be reopened rather than declined outright', () => {
    const actions = allowedQuotationActions({ status: 'accepted' });
    expect(actions).toContain('reopen');
    expect(actions).toContain('convert');
    expect(actions).not.toContain('decline');
    expect(actions).not.toContain('accept');
  });

  it('makes a declined document be reopened before it can convert', () => {
    const actions = allowedQuotationActions({ status: 'declined' });
    expect(actions).toContain('reopen');
    expect(actions).not.toContain('convert');
    expect(actions).not.toContain('edit');
  });

  it('shows nothing that could change a converted document', () => {
    const actions = allowedQuotationActions({ status: 'converted' });
    expect(actions).toEqual(['duplicate', 'share']);
    expect(actions).not.toContain('cancel');
    expect(actions).not.toContain('convert');
  });

  it('leaves only duplicate on a cancelled document', () => {
    expect(allowedQuotationActions({ status: 'cancelled' })).toEqual(['duplicate']);
  });

  it('never offers a payment action on any status', () => {
    for (const status of ['open', 'accepted', 'declined', 'converted', 'cancelled'] as const) {
      for (const action of allowedQuotationActions({ status })) {
        expect(action).not.toMatch(/pay|receipt|paid/i);
      }
    }
  });
});

describe('quotationStatusBadgeClass', () => {
  it('has a class for every chip on the list', () => {
    for (const { value } of QUOTATION_STATUS_FILTERS) {
      expect(quotationStatusBadgeClass(value)).toContain('status-chip');
    }
  });

  it('marks expired as a problem even though its stored status is open', () => {
    expect(quotationStatusBadgeClass('expired')).toBe('status-chip status-chip--expired');
    expect(quotationStatusBadgeClass('open')).toBe('status-chip');
  });
});
