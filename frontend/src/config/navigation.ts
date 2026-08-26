import {
  AlarmClock,
  BookOpen,
  BookUser,
  Boxes,
  Building2,
  ChartColumn,
  Compass,
  DatabaseBackup,
  Factory,
  FileMinus2,
  FileText,
  KeyRound,
  Keyboard,
  Plug,
  LayoutDashboard,
  LayoutList,
  Mail,
  MailCheck,
  Package,
  PackageSearch,
  Percent,
  ReceiptText,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Store,
  Tag,
  Wallet,
  type LucideIcon,
} from 'lucide-react';
import type { ActionKey } from '../utils/shortcutDefaults';

/**
 * Single source of truth for navigation.
 *
 * Sidebar links, document titles, and keyboard-shortcut nav targets all derive
 * from the tables below. Before this existed the three lived in three files and
 * had already drifted — /produce-items and /email-history had no title at all,
 * and '/' was "Dashboard" in the title bar but "Overview" in the sidebar.
 *
 * The shape is deliberately two-level. A flat list had grown to 22 links in six
 * groups, which is more than a rail can be scanned for, so:
 *
 *   - PRIMARY_NAV is at most a handful of rows: a few plain links plus sections
 *     that disclose their children (the sidebar opens one section at a time).
 *   - SETTINGS_GROUPS is everything a user touches once a quarter. Those pages
 *     left the rail entirely and live behind a single /settings entry with
 *     their own sub-navigation.
 *   - HIDDEN_ROUTES is routed-but-unlinked: titled, shortcut-able, never drawn.
 *
 * Routes and guards deliberately stay in App.tsx: it composes four guards in
 * five different combinations, which costs more to express as data than it
 * saves. `adminOnly` here therefore duplicates <AdminOnly> there — it only
 * controls whether a link is *shown*; the route guard remains authoritative.
 */

export type NavLeaf = {
  to: string;
  /** Sidebar label. */
  label: string;
  /** document.title, when it should differ from the sidebar label. */
  title?: string;
  icon: LucideIcon;
  /** NavLink `end` — needed by '/' and by any item with routed children. */
  end?: boolean;
  /** Hide the link from non-admins. Visibility only; see file header. */
  adminOnly?: boolean;
  shortcutAction?: ActionKey;
  /** Child paths that share this item's identity for titling purposes. */
  alsoTitles?: { path: string; title: string }[];
  /** One line of copy. Rendered on the settings overview cards. */
  description?: string;
};

/** A top-level rail row: either a leaf link, or a section that discloses one. */
export type NavEntry =
  | ({ kind: 'link' } & NavLeaf)
  | {
      kind: 'section';
      id: string;
      label: string;
      icon: LucideIcon;
      children: NavLeaf[];
    };

export type SettingsGroup = {
  id: string;
  label: string;
  items: NavLeaf[];
};

export const SETTINGS_ROOT = '/settings';

export const PRIMARY_NAV: NavEntry[] = [
  {
    kind: 'link',
    to: '/',
    label: 'Overview',
    title: 'Dashboard',
    icon: LayoutDashboard,
    end: true,
  },
  {
    kind: 'section',
    id: 'sales',
    label: 'Sales',
    icon: ReceiptText,
    children: [
      { to: '/invoices', label: 'Invoices', icon: FileText, shortcutAction: 'go_invoices' },
      // Labelled for what the page calls itself in its own <h1>; the document
      // title keeps the longer name, which is the more useful one in a tab
      // strip full of invoice pages.
      {
        to: '/invoices-view',
        label: 'Invoice Feed',
        title: 'Advanced Invoice View',
        icon: LayoutList,
      },
      { to: '/invoice-dues', label: 'Invoice Dues', icon: AlarmClock },
      { to: '/credit-notes', label: 'Credit Notes', icon: FileMinus2 },
      {
        to: '/cash-bank',
        label: 'Cash & Bank',
        icon: Wallet,
        alsoTitles: [{ path: '/cash-bank/accounts', title: 'Bank Accounts' }],
      },
    ],
  },
  {
    kind: 'section',
    id: 'catalogue',
    label: 'Catalogue',
    icon: Boxes,
    children: [
      { to: '/products', label: 'Products', icon: Package, shortcutAction: 'go_products' },
      { to: '/inventory', label: 'Inventory', icon: Boxes, shortcutAction: 'go_inventory' },
      {
        to: '/products-inventory',
        label: 'Products & Inventory',
        icon: PackageSearch,
        shortcutAction: 'go_products_inventory',
      },
      { to: '/produce-items', label: 'Produce Items', icon: Factory },
    ],
  },
  {
    kind: 'section',
    id: 'reports',
    label: 'Reports',
    icon: ChartColumn,
    children: [
      { to: '/analytics', label: 'Analytics', icon: ChartColumn, shortcutAction: 'open_reports' },
      { to: '/day-book', label: 'Day Book', icon: BookOpen, shortcutAction: 'go_day_book' },
      { to: '/tax-ledger', label: 'Tax Ledger', icon: Percent, shortcutAction: 'go_tax_ledger' },
    ],
  },
  {
    kind: 'section',
    id: 'marketplace',
    // Shown unconditionally, connection or not — teaching the sidebar about
    // connection state would make it depend on a network call. Each page
    // renders its own "Connect to a marketplace" empty state instead.
    label: 'Marketplace',
    icon: Store,
    children: [
      // `end` because /marketplace/listings and /marketplace/orders are children
      // of this path and would otherwise leave Browse permanently highlighted.
      { to: '/marketplace', label: 'Browse', title: 'Marketplace', icon: Compass, end: true },
      { to: '/marketplace/listings', label: 'My Listings', icon: Tag },
      { to: '/marketplace/orders', label: 'Orders', title: 'Marketplace Orders', icon: ShoppingCart },
    ],
  },
  {
    kind: 'link',
    to: '/ledgers',
    label: 'Ledgers',
    icon: BookUser,
    shortcutAction: 'go_ledgers',
  },
];

/**
 * The one rail row for everything below. Pinned to the footer, not the nav.
 *
 * No `end`: the rail says which *area* you are in, so this stays lit on every
 * /settings/* page. It is the sub-nav's own "All settings" link that needs the
 * exact match, since that one is a sibling of the pages beside it.
 */
export const SETTINGS_ENTRY: NavLeaf = {
  to: SETTINGS_ROOT,
  label: 'Settings',
  icon: Settings,
};

export const SETTINGS_GROUPS: SettingsGroup[] = [
  {
    id: 'organisation',
    label: 'Organisation',
    items: [
      {
        to: '/settings/company',
        label: 'Company',
        title: 'Company Profile',
        icon: Building2,
        description: 'Legal name, GSTIN, address, logo, invoice series and default terms.',
      },
      {
        to: '/settings/marketplace',
        label: 'Marketplace',
        title: 'Marketplace Settings',
        icon: Store,
        adminOnly: true,
        description: 'Connect this instance to the marketplace and control what it syncs.',
      },
    ],
  },
  {
    id: 'communication',
    label: 'Communication',
    items: [
      {
        to: '/settings/email',
        label: 'Email',
        title: 'Email Settings',
        icon: Mail,
        adminOnly: true,
        description: 'SMTP server, sender identity, and a send test before you rely on it.',
      },
      {
        to: '/settings/email-history',
        label: 'Email History',
        icon: MailCheck,
        adminOnly: true,
        description: 'Every message this instance has sent, with its delivery status.',
      },
    ],
  },
  {
    id: 'account',
    label: 'Your account',
    items: [
      {
        to: '/settings/security',
        label: 'Security',
        title: 'Security',
        icon: ShieldCheck,
        description: 'Change the password you sign in with.',
      },
      {
        to: '/settings/shortcuts',
        label: 'Keyboard Shortcuts',
        icon: Keyboard,
        description: 'Rebind the shortcuts you reach for most, or reset them all.',
      },
    ],
  },
  {
    id: 'data',
    label: 'Data & access',
    items: [
      {
        to: '/settings/api-keys',
        label: 'API Keys',
        icon: KeyRound,
        adminOnly: true,
        description: 'Long-lived keys for the MCP server and other integrations.',
      },
      {
        // No `adminOnly`: a grant belongs to the user who consented to it, and
        // every user needs to be able to cut off their own connectors. See the
        // file header — this controls the link only; App.tsx guards the route.
        to: '/settings/connected-apps',
        label: 'Connected Apps',
        icon: Plug,
        description: 'Assistants and apps you have connected, and the access each one holds.',
      },
      {
        to: '/settings/backups',
        label: 'Backups',
        title: 'Database Backups',
        icon: DatabaseBackup,
        adminOnly: true,
        description: 'Take a snapshot of the database, or restore one you took earlier.',
      },
    ],
  },
];

/** Routed and titled, but never drawn in any navigation. */
export const HIDDEN_ROUTES: NavLeaf[] = [
  { to: '/ledgers/new', label: 'New Ledger', icon: BookUser, shortcutAction: 'new_customer' },
];

/**
 * Paths this app used to serve, and where they went. Rendered as redirects in
 * App.tsx so bookmarks, the marketplace's own deep links, and anything a user
 * pasted into a chat before the move all still land.
 */
export const LEGACY_REDIRECTS: Record<string, string> = {
  '/company': '/settings/company',
  '/smtp-settings': '/settings/email',
  '/email-history': '/settings/email-history',
  '/api-keys': '/settings/api-keys',
  '/backups': '/settings/backups',
  '/change-password': '/settings/security',
  '/shortcuts': '/settings/shortcuts',
  '/marketplace/settings': '/settings/marketplace',
};

/** Every registered item, including hidden and settings ones. */
export const NAV_ITEMS: NavLeaf[] = [
  ...PRIMARY_NAV.flatMap((entry) => (entry.kind === 'link' ? [entry] : entry.children)),
  SETTINGS_ENTRY,
  ...SETTINGS_GROUPS.flatMap((group) => group.items),
  ...HIDDEN_ROUTES,
];

/** PRIMARY_NAV with unauthorised items — and any section thereby emptied — dropped. */
export function visiblePrimaryNav(isAdmin: boolean): NavEntry[] {
  return PRIMARY_NAV.flatMap<NavEntry>((entry) => {
    if (entry.kind === 'link') {
      return entry.adminOnly && !isAdmin ? [] : [entry];
    }
    const children = entry.children.filter((item) => !item.adminOnly || isAdmin);
    return children.length > 0 ? [{ ...entry, children }] : [];
  });
}

/** SETTINGS_GROUPS with unauthorised items — and any group thereby emptied — dropped. */
export function visibleSettingsGroups(isAdmin: boolean): SettingsGroup[] {
  return SETTINGS_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.adminOnly || isAdmin),
  })).filter((group) => group.items.length > 0);
}

/**
 * Which rail section owns a path, so the sidebar can open it on arrival.
 *
 * Longest match wins: /marketplace/listings has to beat /marketplace, which is
 * a prefix of it. Returns null for the plain links and for /settings.
 */
export function sectionIdForPath(pathname: string): string | null {
  let bestId: string | null = null;
  let bestLength = 0;

  for (const entry of PRIMARY_NAV) {
    if (entry.kind !== 'section') continue;
    for (const child of entry.children) {
      const matches = child.end
        ? pathname === child.to
        : pathname === child.to || pathname.startsWith(`${child.to}/`);
      if (matches && child.to.length >= bestLength) {
        bestId = entry.id;
        bestLength = child.to.length;
      }
    }
  }

  return bestId;
}

/** Static path -> document title. Hidden and settings items are titled too. */
export const ROUTE_TITLES: Record<string, string> = NAV_ITEMS.reduce<Record<string, string>>(
  (titles, item) => {
    titles[item.to] = item.title ?? item.label;
    for (const child of item.alsoTitles ?? []) {
      titles[child.path] = child.title;
    }
    return titles;
  },
  {},
);

/** Titles for paths with params, which can't be keyed statically. */
const DYNAMIC_TITLES: { test: (pathname: string) => boolean; title: string }[] = [
  { test: (p) => p.startsWith('/ledgers/') && p.endsWith('/edit'), title: 'Edit Ledger' },
  { test: (p) => p.startsWith('/ledgers/'), title: 'View Ledger' },
];

export const FALLBACK_TITLE = 'Simple Invoicing';

export function resolveDocumentTitle(pathname: string): string {
  // Exact registered paths win over the patterns, so /ledgers/new titles as
  // "New Ledger" rather than being caught by the /ledgers/:id rule.
  const exact = ROUTE_TITLES[pathname];
  if (exact) return exact;

  const dynamic = DYNAMIC_TITLES.find((entry) => entry.test(pathname));
  return dynamic ? dynamic.title : FALLBACK_TITLE;
}

/** Nav targets for the keyboard shortcut actions that navigate. */
export const NAV_SHORTCUTS: { action: ActionKey; to: string }[] = NAV_ITEMS.filter(
  (item): item is NavLeaf & { shortcutAction: ActionKey } => item.shortcutAction !== undefined,
).map((item) => ({ action: item.shortcutAction, to: item.to }));
