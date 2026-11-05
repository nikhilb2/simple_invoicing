import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import AuthLayout from './AuthLayout';

describe('AuthLayout', () => {
  it('speaks to a shop owner, not to a developer', () => {
    const html = renderToStaticMarkup(<AuthLayout title="Login">form</AuthLayout>);
    expect(html).toContain('GST-ready tax invoices');
    expect(html).toContain('Send on WhatsApp or email');
    expect(html).toContain('Track your stock');
    expect(html).toContain('See who owes you');
    expect(html).not.toMatch(/JWT|Bearer|backend|frontend|API\b/);
  });
});
