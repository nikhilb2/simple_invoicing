import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import LedgerPhoneLinks from './LedgerPhoneLinks';

describe('LedgerPhoneLinks', () => {
  test('adds direct call and WhatsApp links for a local number', () => {
    const html = renderToStaticMarkup(<LedgerPhoneLinks phone="98765 43210" />);

    expect(html).toContain('href="tel:9876543210"');
    expect(html).toContain('98765 43210');
    expect(html).toContain('href="https://wa.me/919876543210"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('aria-label="Call 98765 43210"');
  });

  test('retains a supplied country code without duplicating it', () => {
    const html = renderToStaticMarkup(<LedgerPhoneLinks phone="+91 (98765) 43210" />);

    expect(html).toContain('href="tel:+919876543210"');
    expect(html).toContain('href="https://wa.me/919876543210"');
  });

  test.each([null, undefined, '', '   '])('omits links for missing phone %s', (phone) => {
    expect(renderToStaticMarkup(<LedgerPhoneLinks phone={phone} />)).toBe('');
  });

  test('does not guess a WhatsApp recipient for uncertain input', () => {
    const html = renderToStaticMarkup(<LedgerPhoneLinks phone="12345" />);

    expect(html).toContain('href="tel:12345"');
    expect(html).toContain('href="https://wa.me/"');
    expect(html).toContain('Choose a contact in WhatsApp');
  });
});
