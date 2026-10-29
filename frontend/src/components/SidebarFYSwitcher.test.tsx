import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import SidebarFYSwitcher from './SidebarFYSwitcher';

const auth = vi.hoisted(() => ({ isAdmin: false }));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, isAdmin: auth.isAdmin }),
}));

vi.mock('../context/FYContext', () => ({
  useFY: () => ({
    activeFY: { id: 2, label: '2026-27', start_date: '2026-04-01', end_date: '2027-03-31', is_active: true },
    fyList: [],
    switchFY: vi.fn(),
    createFY: vi.fn(),
  }),
}));

vi.mock('./CompanySelector', () => ({ default: () => null }));

// The New FY modal is portalled to document.body, which the server renderer
// has no equivalent for; it is closed in these tests anyway.
vi.mock('react-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-dom')>()),
  createPortal: () => null,
}));
vi.stubGlobal('document', { body: {} });

describe('SidebarFYSwitcher', () => {
  beforeEach(() => {
    auth.isAdmin = false;
  });

  test('admins get the dropdown that switches and creates financial years', () => {
    auth.isAdmin = true;
    const html = renderToStaticMarkup(<SidebarFYSwitcher />);

    expect(html).toMatch(/<button[^>]*data-testid="fy-switcher"[^>]*aria-haspopup="listbox"/);
    expect(html).toContain('2026-27');
    expect(html).not.toContain('data-testid="fy-current"');
  });

  test('non-admins see the active year as text, with no control that would return 403', () => {
    const html = renderToStaticMarkup(<SidebarFYSwitcher />);

    expect(html).toMatch(/<p data-testid="fy-current" title="Only an admin can switch or add financial years"[^>]*>2026-27<\/p>/);
    expect(html).not.toContain('fy-switcher');
    expect(html).not.toContain('<button');
  });
});
