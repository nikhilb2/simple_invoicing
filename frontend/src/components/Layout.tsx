import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useLocation, useNavigate } from 'react-router-dom';
import { useShortcuts } from '../context/ShortcutsContext';
import Sidebar from './Sidebar';
import InvoiceCancelDialog from './InvoiceCancelDialog';

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { registerAction } = useShortcuts();
  const navigate = useNavigate();

  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setSidebarOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sidebarOpen]);

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

  return (
    <div className="app-shell">
      <div className="app-shell__sidebar">
        <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      </div>
      {sidebarOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}
      <div className="app-shell__main">
      <div className="app-shell__backdrop app-shell__backdrop--left" />
      <div className="app-shell__backdrop app-shell__backdrop--right" />
      <header className="page-header">
        <button
          className="sidebar-toggle"
          onClick={() => setSidebarOpen(true)}
          aria-label="Open navigation"
        >
          <span className="sidebar-toggle__bar" />
          <span className="sidebar-toggle__bar" />
          <span className="sidebar-toggle__bar" />
        </button>
        <div className="page-header__shortcut-hint">
          Press <kbd>?</kbd> for shortcuts
        </div>
      </header>

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
      <InvoiceCancelDialog />
    </div>
  );
}
