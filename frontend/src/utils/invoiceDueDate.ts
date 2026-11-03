import { formatDate } from './formatting';
import { toIsoDate } from './dateRanges';

export type DueDateMode = 'none' | 'exact' | 'days';

export type DueFilterMode = 'all' | 'overdue' | 'next7' | 'next15' | 'custom-days' | 'exact-date';

export type DueWindow = { dueDateFrom?: string; dueDateTo?: string };

export function addDays(baseDate: Date, days: number): Date {
  const next = new Date(baseDate);
  next.setDate(next.getDate() + days);
  return next;
}

/**
 * The due-date window the Invoice Dues page sends to the API, built from
 * the local calendar date. `today` is injectable for tests and defaults to
 * the real clock. Dates are formatted with the local-date toIsoDate, never
 * toISOString, which would shift every window a day early east of Greenwich.
 */
export function buildDueWindow(
  mode: DueFilterMode,
  customDays: number,
  exactDate: string,
  today: Date = new Date(),
): DueWindow {
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());

  switch (mode) {
    case 'overdue':
      return { dueDateTo: toIsoDate(addDays(startOfToday, -1)) };
    case 'next7':
      return { dueDateFrom: toIsoDate(startOfToday), dueDateTo: toIsoDate(addDays(startOfToday, 7)) };
    case 'next15':
      return { dueDateFrom: toIsoDate(startOfToday), dueDateTo: toIsoDate(addDays(startOfToday, 15)) };
    case 'custom-days':
      return { dueDateFrom: toIsoDate(startOfToday), dueDateTo: toIsoDate(addDays(startOfToday, Math.max(customDays, 0))) };
    case 'exact-date':
      return exactDate ? { dueDateFrom: exactDate, dueDateTo: exactDate } : {};
    case 'all':
    default:
      return {};
  }
}

export type DueDateFormState = {
  mode: DueDateMode;
  exactDate: string;
  daysFromInvoice: string;
};

function parseIsoDateParts(value: string): [number, number, number] | null {
  const parts = value.split('-').map(Number);
  if (parts.length !== 3 || parts.some((part) => Number.isNaN(part))) {
    return null;
  }
  return [parts[0], parts[1], parts[2]];
}

export function addDaysToIsoDate(value: string, days: number): string {
  const parsed = parseIsoDateParts(value);
  if (!parsed) {
    return '';
  }

  const [year, month, day] = parsed;
  const nextDate = new Date(Date.UTC(year, month - 1, day));
  nextDate.setUTCDate(nextDate.getUTCDate() + days);
  return nextDate.toISOString().slice(0, 10);
}

export function resolveDueDate(input: {
  mode: DueDateMode;
  invoiceDate: string;
  exactDate: string;
  daysFromInvoice: string;
}): string | undefined {
  if (input.mode === 'none') {
    return undefined;
  }

  if (input.mode === 'exact') {
    return input.exactDate || undefined;
  }

  const parsedDays = Number.parseInt(input.daysFromInvoice, 10);
  if (Number.isNaN(parsedDays) || parsedDays < 0 || !input.invoiceDate) {
    return undefined;
  }

  return addDaysToIsoDate(input.invoiceDate, parsedDays);
}

export function createDueDateFormState(dueDate?: string | null): DueDateFormState {
  if (!dueDate) {
    return {
      mode: 'none',
      exactDate: '',
      daysFromInvoice: '',
    };
  }

  return {
    mode: 'exact',
    exactDate: dueDate.slice(0, 10),
    daysFromInvoice: '',
  };
}

export function formatInvoiceDateLabel(value: string | null | undefined): string {
  return formatDate(value);
}

/**
 * Label for an invoice that is past its due date, or null when it is not
 * overdue. due_in_days is negative when overdue and null when there is no
 * due date; due today (0) is not overdue.
 */
export function overdueLabel(dueInDays: number | null | undefined): string | null {
  if (dueInDays === null || dueInDays === undefined || dueInDays >= 0) {
    return null;
  }
  const days = Math.abs(dueInDays);
  return days === 1 ? '1 day overdue' : `${days} days overdue`;
}

export type OverdueInvoiceInput = {
  status: string;
  voucher_type?: string | null;
  outstanding_amount: number;
  due_date: string | null;
  due_in_days: number | null;
};

/**
 * Matches the dashboard definition of overdue: an active sales invoice with
 * an amount still outstanding, a due date set, and due_in_days below zero.
 * Paid, cancelled, purchase, due today, and no due date invoices are not
 * overdue. The backend still returns due_in_days for cancelled invoices, so
 * status is checked explicitly.
 */
export function isOverdueInvoice(invoice: OverdueInvoiceInput): boolean {
  return (
    invoice.status === 'active' &&
    invoice.voucher_type === 'sales' &&
    invoice.outstanding_amount > 0 &&
    invoice.due_date !== null &&
    invoice.due_date !== '' &&
    invoice.due_in_days !== null &&
    invoice.due_in_days < 0
  );
}
