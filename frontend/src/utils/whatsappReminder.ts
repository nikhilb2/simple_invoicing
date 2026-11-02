import formatCurrency, { formatDate } from './formatting';

export type WhatsAppReminderDetails = {
  customerName: string | null | undefined;
  invoiceNumber: string;
  outstandingAmount: number;
  currencyCode: string;
  dueDate: string | null | undefined;
  overdue: boolean;
};

/**
 * Prefilled WhatsApp reminder text for one due invoice.
 *
 * Kept pure and separate from the page so the wording is easy to change
 * and to test without rendering. The caller turns this text into a link
 * with buildWhatsAppUrl, which encodes it for wa.me.
 *
 * Wording choice: an overdue invoice says it was due on its due date and
 * is still outstanding, while a not yet due invoice says it is due on its
 * due date. With no due date, both cases say it is still outstanding, so
 * the message never prints a placeholder date.
 */
export function buildWhatsAppReminderMessage(details: WhatsAppReminderDetails): string {
  const name = details.customerName?.trim() || 'there';
  const amount = formatCurrency(details.outstandingAmount, details.currencyCode);
  const dueLabel = details.dueDate ? formatDate(details.dueDate) : null;

  if (details.overdue) {
    if (dueLabel) {
      return `Hi ${name}, a friendly reminder: invoice ${details.invoiceNumber} for ${amount} was due on ${dueLabel} and is still outstanding. Please arrange payment at your earliest convenience. Thank you.`;
    }
    return `Hi ${name}, a friendly reminder: invoice ${details.invoiceNumber} for ${amount} is now overdue and is still outstanding. Please arrange payment at your earliest convenience. Thank you.`;
  }

  if (dueLabel) {
    return `Hi ${name}, a friendly reminder: invoice ${details.invoiceNumber} for ${amount} is due on ${dueLabel}. Please arrange payment by then. Thank you.`;
  }
  return `Hi ${name}, a friendly reminder: invoice ${details.invoiceNumber} for ${amount} is still outstanding. Please arrange payment at your earliest convenience. Thank you.`;
}
