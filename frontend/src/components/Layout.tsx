import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useLocation, useNavigate } from 'react-router-dom';
import { NAV_SHORTCUTS, resolveDocumentTitle } from '../config/navigation';
import { useShortcuts } from '../context/ShortcutsContext';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { useSidebarStore } from '../store/useSidebarStore';
import Sidebar from './Sidebar';
import InvoiceCancelDialog from './InvoiceCancelDialog';

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { registerAction } = useShortcuts();
  const navigate = useNavigate();
  const collapsed = useSidebarStore((state) => state.collapsed);

  // The mobile drawer is ephemeral; only the desktop rail persists.
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const closeSidebar = useCallback(() => setSidebarOpen(false), []);
  useEscapeClose(closeSidebar);

  useEffect(() => {
    const cleanups = NAV_SHORTCUTS.map(({ action, to }) =>
      registerAction(action, () => navigate(to)),
    );
    return () => cleanups.forEach(fn => fn());
  }, [registerAction, navigate]);

  useEffect(() => {
    document.title = `${resolveDocumentTitle(location.pathname)} | Simple Invoicing`;
  }, [location.pathname]);

  return (
    <div className={`app-shell${collapsed ? ' app-shell--rail' : ''}`}>
      <div className="app-shell__sidebar">
        <Sidebar isOpen={sidebarOpen} onClose={closeSidebar} />
      </div>
      {sidebarOpen && (
        <div
          className="sidebar-backdrop"
          onClick={closeSidebar}
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
