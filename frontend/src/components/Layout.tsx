import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useShortcuts } from '../context/ShortcutsContext';
import Sidebar from './Sidebar';

export default function Layout({ children }: { children: React.ReactNode }) {
  const { logout, userEmail, isAdmin } = useAuth();
  const location = useLocation();
  const { registerAction } = useShortcuts();
  const navigate = useNavigate();

  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const cleanups = [
      registerAction('go_invoices',  () => navigate('/invoices')),
      registerAction('go_ledgers',   () => navigate('/ledgers')),
      registerAction('go_products',  () => navigate('/products')),
      registerAction('go_inventory', () => navigate('/inventory')),
      registerAction('go_day_book',  () => navigate('/day-book')),
      registerAction('open_reports', () => navigate('/day-book')),
      registerAction('new_customer', () => navigate('/ledgers/new')),
    ];
    return () => cleanups.forEach(fn => fn());
  }, [registerAction, navigate]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrawerOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawerOpen]);

  const navItems = [
    { to: '/', label: 'Overview' },
    { to: '/products', label: 'Products' },
    { to: '/inventory', label: 'Inventory' },
    { to: '/ledgers', label: 'Ledgers' },
    { to: '/day-book', label: 'Day Book' },
    { to: '/invoices', label: 'Invoices' },
    { to: '/company', label: 'Company' },
    ...(isAdmin ? [{ to: '/smtp-settings', label: 'SMTP Settings' }] : []),
    { to: '/shortcuts', label: 'Keyboard Shortcuts' },
  ];

  return (
    <div className="app-shell">
      <div className="app-shell__sidebar">
        <Sidebar />
      </div>
      <div className="app-shell__main">
      <div className="app-shell__backdrop app-shell__backdrop--left" />
      <div className="app-shell__backdrop app-shell__backdrop--right" />
      <header className="topbar">
        <div className="topbar__top">
          <div>
            <Link to="/" className="brand-mark">Simple Invoicing</Link>
            <p className="topbar__subtitle">
              Stock, billing, and operator workflows in one place.
            </p>
          </div>
          <button
            className="burger-btn"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
          >
            <span className="burger-btn__bar" />
            <span className="burger-btn__bar" />
            <span className="burger-btn__bar" />
          </button>
        </div>
        <div className="topbar__session">
          <div>
            <p className="eyebrow">Signed in as</p>
            <p className="session-email">{userEmail ?? 'Active user'}</p>
          </div>
          <button className="button button--ghost" onClick={logout} title="Logout" aria-label="Logout">
            Logout
          </button>
        </div>
      </header>

      <nav className="section-card nav-panel" aria-label="Primary navigation">
        <div>
          <p className="eyebrow">Navigation</p>
          <p className="nav-panel__title">Control room</p>
        </div>
        <div className="nav-panel__links">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `nav-link${isActive ? ' nav-link--active' : ''}`}
            >
              <span>{item.label}</span>
              {/* <span className="nav-link__hint">{location.pathname === item.to ? 'Current' : 'Open'}</span> */}
            </NavLink>
          ))}
        </div>
      </nav>

      <AnimatePresence>
        {drawerOpen && (
          <>
            <motion.div
              className="drawer-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              onClick={() => setDrawerOpen(false)}
              aria-hidden="true"
            />
            <motion.nav
              className="drawer-panel"
              role="dialog"
              aria-modal="true"
              aria-label="Navigation drawer"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ duration: 0.28, ease: 'easeOut' }}
            >
              <div className="drawer-panel__header">
                <p className="nav-panel__title">Control room</p>
                <button
                  className="drawer-close"
                  onClick={() => setDrawerOpen(false)}
                  aria-label="Close navigation"
                >
                  ✕
                </button>
              </div>
              <div className="drawer-panel__links">
                {navItems.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) => `nav-link${isActive ? ' nav-link--active' : ''}`}
                    onClick={() => setDrawerOpen(false)}
                  >
                    <span>{item.label}</span>
                  </NavLink>
                ))}
              </div>
            </motion.nav>
          </>
        )}
      </AnimatePresence>

      <motion.main
        key={location.pathname}
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.28, ease: 'easeOut' }}
        className="page-frame"
      >
        {children}
      </motion.main>
      </div>
    </div>
  );
}
