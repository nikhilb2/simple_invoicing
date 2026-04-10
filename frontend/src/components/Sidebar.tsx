import { NavLink } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

type NavItem = { to: string; label: string; end?: boolean };

const mainGroup: NavItem[] = [
  { to: '/', label: 'Overview', end: true },
  { to: '/invoices', label: 'Invoices' },
  { to: '/day-book', label: 'Day Book' },
];

const managementGroup: NavItem[] = [
  { to: '/products', label: 'Products' },
  { to: '/inventory', label: 'Inventory' },
  { to: '/ledgers', label: 'Ledgers' },
  { to: '/company', label: 'Company' },
];

const settingsGroup = (isAdmin: boolean): NavItem[] => [
  ...(isAdmin ? [{ to: '/smtp-settings', label: 'SMTP Settings' }] : []),
  { to: '/shortcuts', label: 'Keyboard Shortcuts' },
];

export default function Sidebar() {
  const { isAdmin } = useAuth();

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <div className="sidebar__brand">
          <span>⚡</span>
          <div>
            <span className="sidebar__brand-name">Simple Invoicing</span>
            <span className="sidebar__brand-tagline">Stock &amp; billing</span>
          </div>
        </div>
      </div>

      <nav className="sidebar__nav" aria-label="Sidebar navigation">
        {/* Main group — no label */}
        <div className="sidebar__group">
          {mainGroup.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>

        {/* Management group */}
        <div className="sidebar__group">
          <p className="sidebar__group-label">Management</p>
          {managementGroup.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>

        {/* Settings group */}
        <div className="sidebar__group">
          <p className="sidebar__group-label">Settings</p>
          {settingsGroup(isAdmin).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* footer added in B-3 */}
    </aside>
  );
}

