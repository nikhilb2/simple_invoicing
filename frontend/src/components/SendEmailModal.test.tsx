import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import SendEmailModal, { emailSentMessage } from './SendEmailModal';

describe('emailSentMessage', () => {
  it('names the recipient for each kind of email', () => {
    expect(emailSentMessage('invoice', 'billing@example.com')).toBe('Invoice emailed to billing@example.com');
    expect(emailSentMessage('statement', 'a@b.in')).toBe('Statement emailed to a@b.in');
    expect(emailSentMessage('reminder', 'a@b.in')).toBe('Payment reminder emailed to a@b.in');
  });
});

describe('SendEmailModal', () => {
  it('opens on the form, not on a sent message', () => {
    const html = renderToString(
      <SendEmailModal
        type="invoice"
        entityId={1}
        defaultTo="billing@example.com"
        defaultSubject="Invoice 1"
        onClose={() => {}}
        onSuccess={() => {}}
        onError={() => {}}
      />,
    );
    expect(html).toContain('Send Email');
    expect(html).not.toContain('emailed to');
  });
});
