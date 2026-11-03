import { describe, expect, test } from 'vitest';
import { buildWhatsAppUrl, toWhatsAppNumber } from './phone.ts';
import { buildWhatsAppReminderMessage } from './whatsappReminder.ts';

const base = {
  invoiceNumber: 'INV-42',
  outstandingAmount: 1250.5,
  currencyCode: 'INR',
};

describe('buildWhatsAppReminderMessage', () => {
  test('an overdue invoice names the customer, invoice, amount, and due date', () => {
    const message = buildWhatsAppReminderMessage({
      ...base,
      customerName: 'Asha Sharma',
      dueDate: '2026-10-20',
      overdue: true,
    });
    expect(message).toContain('Asha Sharma');
    expect(message).toContain('INV-42');
    expect(message).toContain('was due on 20-10-2026');
    expect(message).toContain('still outstanding');
    expect(message).toMatch(/₹1,250\.50/);
  });

  test('a not yet due invoice uses due wording instead of overdue wording', () => {
    const message = buildWhatsAppReminderMessage({
      ...base,
      customerName: 'Asha Sharma',
      dueDate: '2026-11-05',
      overdue: false,
    });
    expect(message).toContain('is due on 05-11-2026');
    expect(message).not.toContain('was due on');
    expect(message).not.toContain('overdue');
  });

  test('a missing due date never prints a placeholder date', () => {
    const message = buildWhatsAppReminderMessage({
      ...base,
      customerName: 'Asha Sharma',
      dueDate: null,
      overdue: false,
    });
    expect(message).toContain('is still outstanding');
    expect(message).not.toContain('—');
    expect(message).not.toContain('due on');
  });

  test('a missing customer name falls back to a plain greeting', () => {
    const message = buildWhatsAppReminderMessage({
      ...base,
      customerName: null,
      dueDate: '2026-11-05',
      overdue: false,
    });
    expect(message.startsWith('Hi there,')).toBe(true);
  });

  test('special characters in names survive into the encoded WhatsApp URL', () => {
    const message = buildWhatsAppReminderMessage({
      ...base,
      customerName: "O'Brien & Sons (P) Ltd.",
      dueDate: '2026-11-05',
      overdue: false,
    });
    const url = buildWhatsAppUrl(toWhatsAppNumber('9876543210'), message);
    expect(url).toBe(
      `https://wa.me/919876543210?text=${encodeURIComponent(message)}`,
    );
    expect(url).toContain("O'Brien%20%26%20Sons%20(P)%20Ltd.");
    expect(decodeURIComponent(url.split('?text=')[1])).toBe(message);
  });
});
