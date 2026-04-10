import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { AnimatePresence, motion } from 'framer-motion';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useFY } from '../context/FYContext';
import { useShortcuts } from '../context/ShortcutsContext';
import Sidebar from './Sidebar';

function fyFromStartYear(year: number) {
  const end = year + 1;
  return {
    label: `${year}-${String(end).slice(-2)}`,
    start_date: `${year}-04-01`,
    end_date: `${end}-03-31`,
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const { logout, userEmail, isAdmin } = useAuth();
  const { activeFY, fyList, switchFY, createFY } = useFY();
  const location = useLocation();
  const { registerAction } = useShortcuts();
  const navigate = useNavigate();

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [fyDropdownOpen, setFyDropdownOpen] = useState(false);
  const [newFYModalOpen, setNewFYModalOpen] = useState(false);
  const [newFYStartYear, setNewFYStartYear] = useState('');
  const [newFYError, setNewFYError] = useState('');
  const [newFYSubmitting, setNewFYSubmitting] = useState(false);
  const fyDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!fyDropdownOpen) return;
    const onClickOutside = (e: MouseEvent) => {
      if (fyDropdownRef.current && !fyDropdownRef.current.contains(e.target as Node)) {
        setFyDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [fyDropdownOpen]);

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

        {/* FY Switcher */}
        <div style={{ marginTop: '1.5rem' }}>
          <p className="eyebrow" style={{ marginBottom: '0.5rem' }}>Financial Year</p>
          <div ref={fyDropdownRef} style={{ position: 'relative' }}>
            <button
              className="button button--ghost"
              style={{ width: '100%', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              onClick={() => setFyDropdownOpen((v) => !v)}
              aria-haspopup="listbox"
              aria-expanded={fyDropdownOpen}
            >
              <span>{activeFY ? activeFY.label : 'No active FY'}</span>
              <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>▾</span>
            </button>
            {fyDropdownOpen && (
              <div
                role="listbox"
                style={{
                  position: 'absolute',
                  left: 0,
                  right: 0,
                  top: 'calc(100% + 4px)',
                  background: 'var(--bg-card-strong)',
                  border: '1px solid var(--line-strong)',
                  borderRadius: '0.5rem',
                  boxShadow: '0 4px 24px rgba(0,0,0,0.45)',
                  zIndex: 100,
                  overflow: 'hidden',
                  color: 'var(--text)',
                }}
              >
                {fyList.length === 0 && (
                  <p style={{ padding: '0.5rem 0.75rem', fontSize: '0.85rem', opacity: 0.6 }}>No financial years</p>
                )}
                {fyList.map((fy) => (
                  <button
                    key={fy.id}
                    role="option"
                    aria-selected={fy.is_active}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      width: '100%',
                      textAlign: 'left',
                      padding: '0.5rem 0.75rem',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      fontWeight: fy.is_active ? 700 : 400,
                      fontSize: '0.875rem',
                      color: 'inherit',
                    }}
                    onClick={() => {
                      switchFY(fy.id);
                      setFyDropdownOpen(false);
                    }}
                  >
                    <span style={{ width: '1rem' }}>{fy.is_active ? '✓' : ''}</span>
                    {fy.label}
                  </button>
                ))}
                <hr style={{ margin: '0.25rem 0', border: 'none', borderTop: '1px solid var(--line)' }} />
                <button
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '0.5rem 0.75rem',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: '0.875rem',
                    color: 'inherit',
                    fontWeight: 500,
                  }}
                  onClick={() => {
                    setFyDropdownOpen(false);
                    setNewFYStartYear('');
                    setNewFYError('');
                    setNewFYModalOpen(true);
                  }}
                >
                  + New FY
                </button>
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* New FY Modal */}
      <AnimatePresence>
        {newFYModalOpen && (
          <motion.div
            className="modal-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={(e) => { if (e.target === e.currentTarget) setNewFYModalOpen(false); }}
          >
            <motion.div
              className="modal-panel"
              role="dialog"
              aria-modal="true"
              aria-label="Create new financial year"
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.2 }}
              style={{ maxWidth: '28rem' }}
            >
              <h2 style={{ marginBottom: '1.25rem', fontSize: '1.125rem', fontWeight: 700 }}>New Financial Year</h2>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  const yr = parseInt(newFYStartYear, 10);
                  if (isNaN(yr) || yr < 2000 || yr > 2099) {
                    setNewFYError('Please enter a valid starting year (2000–2099).');
                    return;
                  }
                  const { label, start_date, end_date } = fyFromStartYear(yr);
                  if (fyList.some((fy) => fy.label === label)) {
                    setNewFYError(`Financial year ${label} already exists.`);
                    return;
                  }
                  setNewFYError('');
                  setNewFYSubmitting(true);
                  try {
                    await createFY(label, start_date, end_date);
                    setNewFYModalOpen(false);
                  } catch (err) {
                    if (axios.isAxiosError(err) && err.response?.status === 409) {
                      setNewFYError(`Financial year ${label} already exists.`);
                    } else {
                      setNewFYError('Failed to create financial year. Please try again.');
                    }
                  } finally {
                    setNewFYSubmitting(false);
                  }
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.875rem', fontWeight: 500 }}>
                    Starting year (e.g. 2025)
                    <input
                      className="input"
                      type="number"
                      min="2000"
                      max="2099"
                      value={newFYStartYear}
                      onChange={(e) => setNewFYStartYear(e.target.value)}
                      autoFocus
                    />
                  </label>
                  {newFYStartYear && (() => {
                    const yr = parseInt(newFYStartYear, 10);
                    if (!isNaN(yr) && yr >= 2000 && yr <= 2099) {
                      const p = fyFromStartYear(yr);
                      return (
                        <p style={{ fontSize: '0.825rem', opacity: 0.7, margin: 0 }}>
                          FY {p.label} · Apr 1, {yr} → Mar 31, {yr + 1}
                        </p>
                      );
                    }
                    return null;
                  })()}
                  {newFYError && <p style={{ color: 'var(--error, #ef4444)', fontSize: '0.85rem' }}>{newFYError}</p>}
                  <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                    <button type="button" className="button button--ghost" onClick={() => setNewFYModalOpen(false)}>
                      Cancel
                    </button>
                    <button type="submit" className="button" disabled={newFYSubmitting}>
                      {newFYSubmitting ? 'Creating…' : 'Create'}
                    </button>
                  </div>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

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
