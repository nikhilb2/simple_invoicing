import { describe, expect, it } from 'vitest';
import { describeShareLinkPeriod, describeViews } from './describe';
import type { ShareLink } from '../../types/api';

function link(overrides: Partial<ShareLink>): ShareLink {
  return {
    id: 1,
    token: 'tok',
    url: 'https://example.test/s/tok',
    resource_type: 'ledger_statement',
    resource_id: 7,
    from_date: null,
    to_date: null,
    view_count: 0,
    last_viewed_at: null,
    created_at: '2026-11-01T00:00:00Z',
    ...overrides,
  };
}

describe('describeShareLinkPeriod', () => {
  it('shows both dates for a dated link', () => {
    expect(describeShareLinkPeriod(link({ from_date: '2026-10-01', to_date: '2026-10-31' })))
      .toBe('2026-10-01 to 2026-10-31');
  });

  it('names the open-ended reminder link Always current', () => {
    expect(describeShareLinkPeriod(link({ from_date: null, to_date: null })))
      .toBe('Always current (payment reminders)');
  });

  it('labels a partially dated link from what it has', () => {
    expect(describeShareLinkPeriod(link({ from_date: '2026-10-01', to_date: null })))
      .toBe('From 2026-10-01');
    expect(describeShareLinkPeriod(link({ from_date: null, to_date: '2026-10-31' })))
      .toBe('Until 2026-10-31');
  });
});

describe('describeViews', () => {
  it('reports an unopened link', () => {
    expect(describeViews(0, null)).toBe('Not opened yet');
  });

  it('singularises a single opening', () => {
    expect(describeViews(1, null)).toBe('Opened once');
  });

  it('counts several openings', () => {
    expect(describeViews(4, null)).toBe('Opened 4 times');
  });
});
