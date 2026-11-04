/** Human-readable labels for the email types the backend logs.

Kept in a util (not in the page) so the label map is testable in the
Node-only Vitest setup and so the filter options and the table row both
read from the same map — a new type only has to be added once.
*/
export const EMAIL_TYPE_LABELS: Record<string, string> = {
  invoice: 'Invoice',
  ledger_statement: 'Ledger Statement',
  payment_reminder: 'Payment Reminder',
  due_reminders_batch: 'Due reminders (bulk)',
  other: 'Other',
};

/** The label for a logged email type, or the raw key for an unknown type. */
export function emailTypeLabel(emailType: string): string {
  return EMAIL_TYPE_LABELS[emailType] ?? emailType;
}
