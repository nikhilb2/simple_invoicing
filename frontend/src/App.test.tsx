import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterAll, describe, expect, it, vi } from 'vitest';

const auth = vi.hoisted(() => {
  vi.stubGlobal('localStorage', { getItem: () => null });
  return { isAuthenticated: true, isAdmin: false, canManagePlatform: true };
});

vi.mock('./context/AuthContext', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => auth,
}));
vi.mock('./components/Layout', () => ({
  default: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('./pages/BackupsPage', () => ({ default: () => <h1>Backup settings page</h1> }));
vi.mock('./pages/SmtpSettingsPage', () => ({ default: () => <h1>SMTP settings page</h1> }));

import App from './App';

afterAll(() => vi.unstubAllGlobals());

function render(path: string, hasCompany: boolean) {
  const client = new QueryClient();
  client.setQueryData(['company-setup-required'], hasCompany ? { name: 'Configured Company' } : null);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe.each([
  ['/settings/backups', 'Backup settings page'],
  ['/settings/email', 'SMTP settings page'],
])('platform route %s', (path, heading) => {
  it.each([
    [false, false],
    [false, true],
    [true, false],
    [true, true],
  ])('allows a platform operator (company admin: %s, company: %s)', (isAdmin, hasCompany) => {
    Object.assign(auth, { isAuthenticated: true, isAdmin, canManagePlatform: true });

    const html = render(path, hasCompany);

    expect(html).toContain(`<h1>${heading}</h1>`);
    expect(html).toContain('href="/settings/backups"');
    expect(html).toContain('href="/settings/email"');
  });

  it('denies a company admin without the platform capability', () => {
    Object.assign(auth, { isAuthenticated: true, isAdmin: true, canManagePlatform: false });
    expect(render(path, true)).not.toContain(heading);
  });

  it('still requires a signed-in session', () => {
    Object.assign(auth, { isAuthenticated: false, isAdmin: true, canManagePlatform: true });
    expect(render(path, true)).not.toContain(heading);
  });
});
