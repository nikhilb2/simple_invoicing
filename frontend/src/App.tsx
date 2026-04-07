import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import ProductsPage from './pages/ProductsPage';
import InventoryPage from './pages/InventoryPage';
import InvoicesPage from './pages/InvoicesPage';
import LedgersPage from './pages/LedgersPage';
import LedgerCreatePage from './pages/LedgerCreatePage';
import LedgerViewPage from './pages/LedgerViewPage';
import DayBookPage from './pages/DayBookPage';
import CompanyPage from './pages/CompanyPage';
import SmtpSettingsPage from './pages/SmtpSettingsPage';
import KeyboardShortcutsPage from './pages/KeyboardShortcutsPage';
import Layout from './components/Layout';

function Protected({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return children;
}

function AdminOnly({ children }: { children: React.ReactNode }) {
  const { isAdmin } = useAuth();

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnly>
            <LoginPage />
          </PublicOnly>
        }
      />
      <Route path="/" element={<Protected><Layout><DashboardPage /></Layout></Protected>} />
      <Route path="/products" element={<Protected><Layout><ProductsPage /></Layout></Protected>} />
      <Route path="/inventory" element={<Protected><Layout><InventoryPage /></Layout></Protected>} />
      <Route path="/ledgers" element={<Protected><Layout><LedgersPage /></Layout></Protected>} />
      <Route path="/ledgers/new" element={<Protected><Layout><LedgerCreatePage /></Layout></Protected>} />
      <Route path="/ledgers/:id" element={<Protected><Layout><LedgerViewPage /></Layout></Protected>} />
      <Route path="/ledgers/:id/edit" element={<Protected><Layout><LedgerCreatePage /></Layout></Protected>} />
      <Route path="/day-book" element={<Protected><Layout><DayBookPage /></Layout></Protected>} />
      <Route path="/invoices" element={<Protected><Layout><InvoicesPage /></Layout></Protected>} />
      <Route path="/company" element={<Protected><Layout><CompanyPage /></Layout></Protected>} />
      <Route path="/keyboard-shortcuts" element={<Protected><Layout><KeyboardShortcutsPage /></Layout></Protected>} />
      <Route path="/smtp-settings" element={<Protected><AdminOnly><Layout><SmtpSettingsPage /></Layout></AdminOnly></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
