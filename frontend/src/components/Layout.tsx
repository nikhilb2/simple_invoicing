import { useState } from 'react';
import { motion } from 'framer-motion';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import StatusToasts from './StatusToasts';
import ShortcutLauncher from './ShortcutLauncher';

export default function Layout({ children }: { children: React.ReactNode }) {
  const { logout, userEmail, isAdmin } = useAuth();
  const location = useLocation();
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const navItems = [
    { to: '/', label: 'Overview' },
    { to: '/products', label: 'Products' },
    { to: '/inventory', label: 'Inventory' },
    { to: '/ledgers', label: 'Ledgers' },
    { to: '/day-book', label: 'Day Book' },
    { to: '/invoices', label: 'Invoices' },
    { to: '/company', label: 'Company' },
    ...(isAdmin ? [{ to: '/smtp-settings', label: 'SMTP Settings' }] : []),
  ];

  return (
    <div className="app-shell">
      <div className="app-shell__backdrop app-shell__backdrop--left" />
      <div className="app-shell__backdrop app-shell__backdrop--right" />
      <header className="topbar">
        <div>
          <Link to="/" className="brand-mark">Simple Invoicing</Link>
          <p className="topbar__subtitle">
            Stock, billing, and operator workflows in one place.
          </p>
        </div>
        <div className="topbar__session">
          <ShortcutLauncher onError={setError} onSuccess={setSuccess} />
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

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

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
  );
}
