import { describe, expect, test } from 'vitest';
import { EMAIL_TYPE_LABELS, emailTypeLabel } from './emailTypes.ts';

describe('EMAIL_TYPE_LABELS', () => {
  test.each([
    'invoice',
    'ledger_statement',
    'payment_reminder',
    'due_reminders_batch',
    'other',
  ])('%s has a readable label', (emailType) => {
    const label = EMAIL_TYPE_LABELS[emailType];
    expect(label).toBeTruthy();
    expect(label).not.toBe(emailType);
  });

  test('unknown types fall back to the raw key in the table', () => {
    expect(emailTypeLabel('something_new')).toBe('something_new');
  });
});
