import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import OAuthButtons from './OAuthButtons';

const google = { id: 'google', name: 'Google' };

describe('OAuthButtons', () => {
  it('renders nothing when no provider is enabled', () => {
    expect(renderToString(<OAuthButtons providers={[]} next="/" />)).toBe('');
  });

  it('shows the logo beside the label, as decoration for screen readers', () => {
    const html = renderToString(<OAuthButtons providers={[google]} next="/" label="Sign up with" />);

    expect(html).toContain('src="/google-g.svg"');
    expect(html).toContain('alt=""');
    expect(html).toContain('oauth-button--google');
    expect(html.replace(/<!-- -->/g, '')).toContain('Sign up with Google');
  });

  it('links to the provider, carrying the destination', () => {
    const html = renderToString(<OAuthButtons providers={[google]} next="/invoices" />);

    expect(html).toContain('/auth/oauth/google/login?next=%2Finvoices');
  });

  it('still offers a provider that has no logo', () => {
    const html = renderToString(<OAuthButtons providers={[{ id: 'other', name: 'Other' }]} next="/" />);

    expect(html.replace(/<!-- -->/g, '')).toContain('Continue with Other');
    expect(html).not.toContain('<img');
  });
});
