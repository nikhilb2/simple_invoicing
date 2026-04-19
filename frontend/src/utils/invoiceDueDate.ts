export type DueDateMode = 'none' | 'exact' | 'days';

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
  if (!value) {
    return '\u2014';
  }
  return new Date(value).toLocaleDateString();
}