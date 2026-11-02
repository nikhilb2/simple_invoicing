import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import LedgerCardPhoneChips from './LedgerCardPhoneChips';

describe('LedgerCardPhoneChips', () => {
  test('adds direct call and WhatsApp chips for a local number', () => {
    const html = renderToStaticMarkup(<LedgerCardPhoneChips phone="98765 43210" />);

    expect(html).toContain('href="tel:9876543210"');
    expect(html).toContain('98765 43210');
    expect(html).toContain('href="https://wa.me/919876543210"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('aria-label="Call 98765 43210"');
    expect(html).toContain('WhatsApp');
  });

  test('retains a supplied country code without duplicating it', () => {
    const html = renderToStaticMarkup(<LedgerCardPhoneChips phone="+91 (98765) 43210" />);

    expect(html).toContain('href="tel:+919876543210"');
    expect(html).toContain('href="https://wa.me/919876543210"');
  });

  test('shows only the call chip for an uncertain number', () => {
    const html = renderToStaticMarkup(<LedgerCardPhoneChips phone="12345" />);

    expect(html).toContain('href="tel:12345"');
    expect(html).not.toContain('wa.me');
    expect(html).not.toContain('WhatsApp');
  });

  test('keeps a no-digit value as a plain, non-link chip', () => {
    const html = renderToStaticMarkup(<LedgerCardPhoneChips phone="not a number" />);

    expect(html).toContain('not a number');
    expect(html).not.toContain('href=');
    expect(html).not.toContain('WhatsApp');
  });

  test.each([null, undefined, '', '   '])('renders nothing for missing phone %s', (phone) => {
    expect(renderToStaticMarkup(<LedgerCardPhoneChips phone={phone} />)).toBe('');
  });
});
