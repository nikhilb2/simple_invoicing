import { describe, expect, it } from 'vitest';
import {
  FALLBACK_TITLE,
  NAV_ITEMS,
  NAV_SHORTCUTS,
  ROUTE_TITLES,
  resolveDocumentTitle,
  visibleNavGroups,
} from './navigation';
import { ACTION_KEYS } from '../utils/shortcutDefaults';

describe('resolveDocumentTitle', () => {
  it('titles a static route from its nav item', () => {
    expect(resolveDocumentTitle('/invoices')).toBe('Invoices');
  });

  it('prefers an explicit title over the sidebar label', () => {
    // The sidebar says "Overview"; the title bar has always said "Dashboard".
    expect(resolveDocumentTitle('/')).toBe('Dashboard');
    expect(resolveDocumentTitle('/company')).toBe('Company Profile');
  });

  it('titles the routes that the old hand-written map had missed', () => {
    expect(resolveDocumentTitle('/produce-items')).toBe('Produce Items');
    expect(resolveDocumentTitle('/email-history')).toBe('Email History');
  });

  it('titles hidden routes', () => {
    expect(resolveDocumentTitle('/invoices-view')).toBe('Advanced Invoice View');
  });

  it('titles child paths declared via alsoTitles', () => {
    expect(resolveDocumentTitle('/cash-bank/accounts')).toBe('Bank Accounts');
  });

  it('titles dynamic ledger routes', () => {
    expect(resolveDocumentTitle('/ledgers/42')).toBe('View Ledger');
    expect(resolveDocumentTitle('/ledgers/42/edit')).toBe('Edit Ledger');
  });

  it('prefers an exact match over the dynamic ledger patterns', () => {
    expect(resolveDocumentTitle('/ledgers/new')).toBe('New Ledger');
    expect(resolveDocumentTitle('/ledgers')).toBe('Ledgers');
  });

  it('falls back for unknown paths', () => {
    expect(resolveDocumentTitle('/nope')).toBe(FALLBACK_TITLE);
  });
});

describe('visibleNavGroups', () => {
  it('hides admin-only items from non-admins', () => {
    const paths = visibleNavGroups(false).flatMap((group) => group.items.map((item) => item.to));
    expect(paths).not.toContain('/api-keys');
    expect(paths).not.toContain('/smtp-settings');
    expect(paths).toContain('/change-password');
  });

  it('shows admin-only items to admins', () => {
    const paths = visibleNavGroups(true).flatMap((group) => group.items.map((item) => item.to));
    expect(paths).toContain('/api-keys');
    expect(paths).toContain('/smtp-settings');
  });

  it('never surfaces hidden items', () => {
    for (const isAdmin of [true, false]) {
      const paths = visibleNavGroups(isAdmin).flatMap((group) => group.items.map((item) => item.to));
      expect(paths).not.toContain('/invoices-view');
      expect(paths).not.toContain('/ledgers/new');
    }
  });

  it('still titles hidden items even though they are not linked', () => {
    expect(ROUTE_TITLES['/invoices-view']).toBeDefined();
    expect(ROUTE_TITLES['/ledgers/new']).toBeDefined();
  });

  it('drops groups left empty after filtering', () => {
    for (const group of visibleNavGroups(false)) {
      expect(group.items.length).toBeGreaterThan(0);
    }
  });

  it('exposes an Analytics group containing the analytics route', () => {
    const analytics = visibleNavGroups(false).find((group) => group.id === 'analytics');
    expect(analytics?.label).toBe('Analytics');
    expect(analytics?.items.map((item) => item.to)).toContain('/analytics');
  });

  it('gives every item an icon', () => {
    for (const item of NAV_ITEMS) {
      expect(item.icon).toBeDefined();
    }
  });
});

describe('NAV_SHORTCUTS', () => {
  it('only uses action keys the shortcut system knows about', () => {
    // TypeScript enforces this too, but the backend keeps its own DEFAULTS dict
    // and rejects unknown keys with a 400 — so adding a nav shortcut means
    // touching backend/src/api/routes/shortcuts.py as well.
    for (const { action } of NAV_SHORTCUTS) {
      expect(ACTION_KEYS).toContain(action);
    }
  });

  it('points every shortcut at a registered route', () => {
    const paths = NAV_ITEMS.map((item) => item.to);
    for (const { to } of NAV_SHORTCUTS) {
      expect(paths).toContain(to);
    }
  });

  it('declares no duplicate actions', () => {
    const actions = NAV_SHORTCUTS.map((entry) => entry.action);
    expect(new Set(actions).size).toBe(actions.length);
  });

  it('routes open_reports to analytics', () => {
    // It used to land on /day-book, which was never what the name meant.
    expect(NAV_SHORTCUTS.find((entry) => entry.action === 'open_reports')?.to).toBe('/analytics');
  });
});
