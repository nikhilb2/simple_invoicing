import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { AnimatePresence, motion } from 'framer-motion';
import { Link, NavLink } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useFY } from '../context/FYContext';

type NavItem = { to: string; label: string; end?: boolean };

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

const mainGroup: NavItem[] = [
  { to: '/', label: 'Overview', end: true },
  { to: '/invoices', label: 'Invoices' },
  { to: '/credit-notes', label: 'Credit Notes' },
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
  ...(isAdmin ? [{ to: '/backups', label: 'Backups' }] : []),
  { to: '/shortcuts', label: 'Keyboard Shortcuts' },
];

function fyFromStartYear(year: number) {
  const end = year + 1;
  return {
    label: `${year}-${String(end).slice(-2)}`,
    start_date: `${year}-04-01`,
    end_date: `${end}-03-31`,
  };
}

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const { isAdmin, userEmail, logout } = useAuth();
  const { activeFY, fyList, switchFY, createFY } = useFY();

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
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  return (
    <>
      <aside
        className={`sidebar${isOpen ? ' sidebar--open' : ''}`}
        {...(isOpen ? { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Navigation drawer' } : {})}
      >
        <div className="sidebar__header">
          <button
            className="sidebar__close"
            onClick={onClose}
            aria-label="Close navigation"
          >
            ✕
          </button>
          <Link to="/" className="sidebar__brand" onClick={() => onClose?.()}>
            <span>⚡</span>
            <div>
              <span className="sidebar__brand-name">Simple Invoicing</span>
              <span className="sidebar__brand-tagline">Stock &amp; billing</span>
            </div>
          </Link>
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
                onClick={() => onClose?.()}
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
                onClick={() => onClose?.()}
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
                onClick={() => onClose?.()}
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>

        {/* FY section — above footer */}
        <div style={{ padding: '12px 10px', borderTop: '1px solid var(--sidebar-border)' }}>
          <p className="sidebar__group-label" style={{ marginBottom: '6px' }}>Financial Year</p>
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

        <div className="sidebar__footer">
          <div className="sidebar__user">
            <div className="sidebar__user-avatar">
              {userEmail ? userEmail[0].toUpperCase() : 'U'}
            </div>
            <div>
              <span className="sidebar__user-email">{userEmail ?? 'Active user'}</span>
              <span className="sidebar__user-role">{isAdmin ? 'Admin' : 'User'}</span>
            </div>
          </div>
          <button className="button button--ghost" onClick={logout}>
            Logout
          </button>
        </div>
      </aside>

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
    </>
  );
}

