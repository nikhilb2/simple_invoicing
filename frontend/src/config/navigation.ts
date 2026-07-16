import {
  AlarmClock,
  BookOpen,
  Boxes,
  Building2,
  ChartColumn,
  DatabaseBackup,
  Factory,
  FileMinus2,
  FileText,
  KeyRound,
  Keyboard,
  LayoutDashboard,
  Lock,
  Mail,
  MailCheck,
  Package,
  PackageSearch,
  Percent,
  Users,
  Wallet,
  type LucideIcon,
} from 'lucide-react';
import type { ActionKey } from '../utils/shortcutDefaults';

/**
 * Single source of truth for navigation.
 *
 * Sidebar links, document titles, and keyboard-shortcut nav targets all derive
 * from NAV_GROUPS below. Before this existed the three lived in three files and
 * had already drifted — /produce-items and /email-history had no title at all,
 * and '/' was "Dashboard" in the title bar but "Overview" in the sidebar.
 *
 * Routes and guards deliberately stay in App.tsx: it composes four guards in
 * five different combinations, which costs more to express as data than it
 * saves. `adminOnly` here therefore duplicates <AdminOnly> there — it only
 * controls whether a link is *shown*; the route guard remains authoritative.
 */

export type NavItem = {
  to: string;
  /** Sidebar label. */
  label: string;
  /** document.title, when it should differ from the sidebar label. */
  title?: string;
  icon: LucideIcon;
  /** NavLink `end` — only '/' needs it. */
  end?: boolean;
  /** Hide the link from admins-only users. Visibility only; see file header. */
  adminOnly?: boolean;
  /** Routed but intentionally not linked in the sidebar. */
  hidden?: boolean;
  shortcutAction?: ActionKey;
  /** Child paths that share this item's identity for titling purposes. */
  alsoTitles?: { path: string; title: string }[];
};

export type NavGroup = {
  id: string;
  /** null renders the group without a heading. */
  label: string | null;
  items: NavItem[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    id: 'main',
    label: null,
    items: [
      { to: '/', label: 'Overview', title: 'Dashboard', icon: LayoutDashboard, end: true },
      { to: '/invoices', label: 'Invoices', icon: FileText, shortcutAction: 'go_invoices' },
      { to: '/invoice-dues', label: 'Invoice Dues', icon: AlarmClock },
      { to: '/credit-notes', label: 'Credit Notes', icon: FileMinus2 },
      {
        to: '/cash-bank',
        label: 'Cash & Bank',
        icon: Wallet,
        alsoTitles: [{ path: '/cash-bank/accounts', title: 'Bank Accounts' }],
      },
      { to: '/invoices-view', label: 'Advanced Invoice View', icon: FileText, hidden: true },
    ],
  },
  {
    id: 'analytics',
    label: 'Analytics',
    // Day Book and Tax Ledger live here rather than under the main group: they
    // are reports, and grouping them keeps Analytics from being a lone item.
    items: [
      { to: '/analytics', label: 'Analytics', icon: ChartColumn, shortcutAction: 'open_reports' },
      { to: '/day-book', label: 'Day Book', icon: BookOpen, shortcutAction: 'go_day_book' },
      { to: '/tax-ledger', label: 'Tax Ledger', icon: Percent, shortcutAction: 'go_tax_ledger' },
    ],
  },
  {
    id: 'catalogue',
    label: 'Catalogue',
    items: [
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
    id: 'organisation',
    label: 'Organisation',
    items: [
      { to: '/ledgers', label: 'Ledgers', icon: Users, shortcutAction: 'go_ledgers' },
      { to: '/ledgers/new', label: 'New Ledger', icon: Users, hidden: true, shortcutAction: 'new_customer' },
      { to: '/company', label: 'Company', title: 'Company Profile', icon: Building2 },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    items: [
      { to: '/smtp-settings', label: 'SMTP Settings', title: 'Email Settings', icon: Mail, adminOnly: true },
      { to: '/backups', label: 'Backups', title: 'Database Backups', icon: DatabaseBackup, adminOnly: true },
      { to: '/email-history', label: 'Email History', icon: MailCheck, adminOnly: true },
      { to: '/api-keys', label: 'API Keys', icon: KeyRound, adminOnly: true },
      { to: '/change-password', label: 'Change Password', title: 'Security', icon: Lock },
      { to: '/shortcuts', label: 'Keyboard Shortcuts', icon: Keyboard },
    ],
  },
];

/** Every registered item, including hidden ones. */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);

/** Groups with hidden/unauthorised items removed, and emptied groups dropped. */
export function visibleNavGroups(isAdmin: boolean): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.hidden && (!item.adminOnly || isAdmin)),
  })).filter((group) => group.items.length > 0);
}

/** Static path -> document title. Hidden items are titled too. */
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
  (item): item is NavItem & { shortcutAction: ActionKey } => item.shortcutAction !== undefined,
).map((item) => ({ action: item.shortcutAction, to: item.to }));
