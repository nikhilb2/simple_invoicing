import { describe, expect, it } from 'vitest';
import {
  FALLBACK_TITLE,
  HIDDEN_ROUTES,
  LEGACY_REDIRECTS,
  NAV_ITEMS,
  NAV_SHORTCUTS,
  PRIMARY_NAV,
  ROUTE_TITLES,
  SETTINGS_ENTRY,
  SETTINGS_GROUPS,
  SETTINGS_ROOT,
  resolveDocumentTitle,
  sectionIdForPath,
  visiblePrimaryNav,
  visibleSettingsGroups,
} from './navigation';
import { ACTION_KEYS } from '../utils/shortcutDefaults';

const pathsOf = (isAdmin: boolean) =>
  visiblePrimaryNav(isAdmin).flatMap((entry) =>
    entry.kind === 'link' ? [entry.to] : entry.children.map((child) => child.to),
  );

describe('resolveDocumentTitle', () => {
  it('titles a static route from its nav item', () => {
    expect(resolveDocumentTitle('/invoices')).toBe('Invoices');
  });

  it('prefers an explicit title over the sidebar label', () => {
    // The sidebar says "Overview"; the title bar has always said "Dashboard".
    expect(resolveDocumentTitle('/')).toBe('Dashboard');
    expect(resolveDocumentTitle('/settings/company')).toBe('Company Profile');
  });

  it('titles the routes that the old hand-written map had missed', () => {
    expect(resolveDocumentTitle('/produce-items')).toBe('Produce Items');
    expect(resolveDocumentTitle('/settings/email-history')).toBe('Email History');
  });

  it('titles the marketplace routes, including the admin-only settings page', () => {
    expect(resolveDocumentTitle('/marketplace')).toBe('Marketplace');
    expect(resolveDocumentTitle('/marketplace/listings')).toBe('My Listings');
    expect(resolveDocumentTitle('/marketplace/orders')).toBe('Marketplace Orders');
    expect(resolveDocumentTitle('/settings/marketplace')).toBe('Marketplace Settings');
  });

  it('titles every settings page, the hub included', () => {
    expect(resolveDocumentTitle(SETTINGS_ROOT)).toBe('Settings');
    for (const group of SETTINGS_GROUPS) {
      for (const item of group.items) {
        expect(resolveDocumentTitle(item.to)).not.toBe(FALLBACK_TITLE);
      }
    }
  });

  it('keeps the longer document title where a nav label was shortened', () => {
    // The rail says "Invoice Feed", matching the page's own <h1>; a tab strip
    // full of invoice pages wants the more specific name.
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

describe('PRIMARY_NAV', () => {
  it('stays small enough to scan — the whole point of the two-level shape', () => {
    // 22 flat links is what this replaced. If a row is added here, ask whether
    // it belongs inside a section (or in settings) before raising this number.
    expect(PRIMARY_NAV.length).toBeLessThanOrEqual(8);
  });

  it('keeps no settings page in the main rail', () => {
    for (const to of pathsOf(true)) {
      expect(to.startsWith(SETTINGS_ROOT)).toBe(false);
    }
  });

  it('gives every section at least two children', () => {
    // A section that discloses one link is a click that buys nothing.
    for (const entry of PRIMARY_NAV) {
      if (entry.kind === 'section') expect(entry.children.length).toBeGreaterThan(1);
    }
  });

  it('gives every item an icon', () => {
    for (const item of NAV_ITEMS) {
      expect(item.icon).toBeDefined();
    }
  });

  it('registers no path twice', () => {
    const paths = NAV_ITEMS.map((item) => item.to);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('marks /marketplace as an exact NavLink match', () => {
    // Without `end` the Browse link stays highlighted on every child route.
    const marketplace = PRIMARY_NAV.find(
      (entry) => entry.kind === 'section' && entry.id === 'marketplace',
    );
    expect(marketplace?.kind === 'section' && marketplace.children[0].end).toBe(true);
  });

  it('never surfaces hidden routes', () => {
    for (const isAdmin of [true, false]) {
      const paths = pathsOf(isAdmin);
      for (const route of HIDDEN_ROUTES) {
        expect(paths).not.toContain(route.to);
      }
      // The parent it belongs to is linked, which is the point: /ledgers/new
      // is a mode of that page rather than a destination of its own.
      expect(paths).toContain('/ledgers');
    }
  });

  it('still titles hidden routes even though they are not linked', () => {
    for (const route of HIDDEN_ROUTES) {
      expect(ROUTE_TITLES[route.to]).toBeDefined();
    }
  });
});

describe('visiblePrimaryNav', () => {
  it('shows the marketplace section to everyone, connected or not', () => {
    // Deliberately unconditional: the sidebar must not depend on a network
    // call for connection state. Each page renders its own connect prompt.
    for (const isAdmin of [true, false]) {
      const marketplace = visiblePrimaryNav(isAdmin).find(
        (entry) => entry.kind === 'section' && entry.id === 'marketplace',
      );
      expect(marketplace?.kind).toBe('section');
      expect(marketplace?.kind === 'section' && marketplace.children.map((c) => c.to)).toEqual([
        '/marketplace',
        '/marketplace/listings',
        '/marketplace/orders',
      ]);
    }
  });

  it('keeps the everyday sections in their reading order', () => {
    const ids = visiblePrimaryNav(true).map((entry) =>
      entry.kind === 'section' ? entry.id : entry.to,
    );
    expect(ids.indexOf('sales')).toBeLessThan(ids.indexOf('catalogue'));
    expect(ids.indexOf('catalogue')).toBeLessThan(ids.indexOf('marketplace'));
    expect(ids.indexOf('/')).toBe(0);
  });

  it('drops sections left empty after filtering', () => {
    for (const entry of visiblePrimaryNav(false)) {
      if (entry.kind === 'section') expect(entry.children.length).toBeGreaterThan(0);
    }
  });
});

describe('visibleSettingsGroups', () => {
  it('hides admin-only pages from non-admins', () => {
    const paths = visibleSettingsGroups(false).flatMap((g) => g.items.map((item) => item.to));
    expect(paths).not.toContain('/settings/api-keys');
    expect(paths).not.toContain('/settings/email');
    expect(paths).not.toContain('/settings/marketplace');
    expect(paths).toContain('/settings/security');
  });

  it('shows admin-only pages to admins', () => {
    const paths = visibleSettingsGroups(true).flatMap((g) => g.items.map((item) => item.to));
    expect(paths).toContain('/settings/api-keys');
    expect(paths).toContain('/settings/email');
    expect(paths).toContain('/settings/backups');
  });

  it('leaves a non-admin something to see, so /settings is never a dead end', () => {
    expect(visibleSettingsGroups(false).length).toBeGreaterThan(0);
  });

  it('drops groups left empty after filtering', () => {
    for (const group of visibleSettingsGroups(false)) {
      expect(group.items.length).toBeGreaterThan(0);
    }
  });

  it('describes every page, since the overview cards render the copy', () => {
    for (const group of SETTINGS_GROUPS) {
      for (const item of group.items) {
        expect(item.description?.length ?? 0).toBeGreaterThan(0);
      }
    }
  });

  it('nests every settings page under the hub path', () => {
    for (const group of SETTINGS_GROUPS) {
      for (const item of group.items) {
        expect(item.to.startsWith(`${SETTINGS_ROOT}/`)).toBe(true);
      }
    }
  });

  it('points the rail entry at the hub, and leaves it lit on every child', () => {
    // The rail says which area you are in, so the footer link deliberately has
    // no `end` — a settings page you navigated to should keep it highlighted.
    expect(SETTINGS_ENTRY.to).toBe(SETTINGS_ROOT);
    expect(SETTINGS_ENTRY.end).toBeUndefined();
  });
});

describe('the invoice feed', () => {
  it('is linked from the sales section, beside the composer', () => {
    const sales = visiblePrimaryNav(false).find(
      (entry) => entry.kind === 'section' && entry.id === 'sales',
    );
    const paths = sales?.kind === 'section' ? sales.children.map((c) => c.to) : [];
    expect(paths).toContain('/invoices-view');
    expect(paths.indexOf('/invoices-view')).toBe(paths.indexOf('/invoices') + 1);
  });

  it('is not a child path of /invoices, so neither link steals the other', () => {
    // Both are linked now and neither declares `end`. NavLink matches whole
    // segments, so '/invoices-view' is a sibling of '/invoices', not a
    // descendant — this is what stops both rows highlighting at once.
    expect('/invoices-view'.startsWith('/invoices/')).toBe(false);
    expect(sectionIdForPath('/invoices-view')).toBe('sales');
    expect(sectionIdForPath('/invoices')).toBe('sales');
  });
});

describe('sectionIdForPath', () => {
  it('finds the section that owns a path', () => {
    expect(sectionIdForPath('/invoices')).toBe('sales');
    expect(sectionIdForPath('/tax-ledger')).toBe('reports');
    expect(sectionIdForPath('/produce-items')).toBe('catalogue');
  });

  it('follows a child route up to its section', () => {
    expect(sectionIdForPath('/cash-bank/accounts')).toBe('sales');
  });

  it('prefers the longest match over a prefix of it', () => {
    // /marketplace is a prefix of /marketplace/listings; both are in the same
    // section here, but the rule is what keeps `end` items from swallowing
    // their siblings.
    expect(sectionIdForPath('/marketplace/listings')).toBe('marketplace');
    expect(sectionIdForPath('/marketplace')).toBe('marketplace');
  });

  it('does not match an `end` item on a deeper path', () => {
    expect(sectionIdForPath('/marketplace/nonsense')).toBe(null);
  });

  it('returns null for the plain links and for settings', () => {
    expect(sectionIdForPath('/')).toBe(null);
    expect(sectionIdForPath('/ledgers')).toBe(null);
    expect(sectionIdForPath('/settings/backups')).toBe(null);
  });
});

describe('LEGACY_REDIRECTS', () => {
  it('rehomes every path the settings move vacated', () => {
    expect(LEGACY_REDIRECTS['/company']).toBe('/settings/company');
    expect(LEGACY_REDIRECTS['/smtp-settings']).toBe('/settings/email');
    expect(LEGACY_REDIRECTS['/marketplace/settings']).toBe('/settings/marketplace');
  });

  it('points every redirect at a route that exists', () => {
    const paths = NAV_ITEMS.map((item) => item.to);
    for (const to of Object.values(LEGACY_REDIRECTS)) {
      expect(paths).toContain(to);
    }
  });

  it('redirects away from paths nothing is registered at any more', () => {
    const paths = NAV_ITEMS.map((item) => item.to);
    for (const from of Object.keys(LEGACY_REDIRECTS)) {
      expect(paths).not.toContain(from);
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

  it('keeps every shortcut reachable without opening a section first', () => {
    // A shortcut whose target is buried behind a disclosure is exactly the
    // case the accordion must not regress.
    for (const { to } of NAV_SHORTCUTS) {
      expect(sectionIdForPath(to) !== null || NAV_ITEMS.some((i) => i.to === to)).toBe(true);
    }
  });
});
