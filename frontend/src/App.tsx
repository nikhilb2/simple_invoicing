import { Navigate, Route, Routes } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './context/AuthContext';
import { FYProvider } from './context/FYContext';
import { ShortcutsProvider } from './context/ShortcutsContext';
import api from './api/client';
import type { CompanyProfile } from './types/api';
import { isCompanyConfigured } from './utils/companySetup';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import ProductsPage from './pages/ProductsPage';
import InventoryPage from './pages/InventoryPage';
import InvoicesPage from './pages/InvoicesPage';
import InvoicesAdvancedView from './pages/InvoicesAdvancedView';
import CreditNotesPage from './pages/CreditNotesPage';
import LedgersPage from './pages/LedgersPage';
import LedgerCreatePage from './pages/LedgerCreatePage';
import LedgerViewPage from './pages/LedgerViewPage';
import DayBookPage from './pages/DayBookPage';
import CashBankPage from './pages/CashBankPage';
import CashBankAccountsPage from './pages/CashBankAccountsPage';
import CompanyPage from './pages/CompanyPage';
import SmtpSettingsPage from './pages/SmtpSettingsPage';
import BackupsPage from './pages/BackupsPage';
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

function CompanyRequired({ children }: { children: React.ReactNode }) {
  const companyQuery = useQuery({
    queryKey: ['company-setup-required'],
    queryFn: async () => {
      const response = await api.get<CompanyProfile>('/company/');
      return response.data;
    },
    retry: false,
  });

  if (companyQuery.isLoading) {
    return <div className="empty-state">Loading company profile...</div>;
  }

  if (companyQuery.error) {
    return children;
  }

  if (!isCompanyConfigured(companyQuery.data)) {
    return <Navigate to="/company?setup=required" replace />;
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
      <Route path="/" element={<Protected><CompanyRequired><Layout><DashboardPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/products" element={<Protected><CompanyRequired><Layout><ProductsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/inventory" element={<Protected><CompanyRequired><Layout><InventoryPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers" element={<Protected><CompanyRequired><Layout><LedgersPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/new" element={<Protected><CompanyRequired><Layout><LedgerCreatePage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/:id" element={<Protected><CompanyRequired><Layout><LedgerViewPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/:id/edit" element={<Protected><CompanyRequired><Layout><LedgerCreatePage /></Layout></CompanyRequired></Protected>} />
      <Route path="/day-book" element={<Protected><CompanyRequired><Layout><DayBookPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/cash-bank" element={<Protected><CompanyRequired><Layout><CashBankPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/cash-bank/accounts" element={<Protected><CompanyRequired><Layout><CashBankAccountsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/invoices" element={<Protected><CompanyRequired><Layout><InvoicesPage /></Layout></CompanyRequired></Protected>} />
        <Route path="/invoices-view" element={<Protected><CompanyRequired><Layout><InvoicesAdvancedView /></Layout></CompanyRequired></Protected>} />
      <Route path="/credit-notes" element={<Protected><CompanyRequired><Layout><CreditNotesPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/company" element={<Protected><Layout><CompanyPage /></Layout></Protected>} />
      <Route path="/smtp-settings" element={<Protected><CompanyRequired><AdminOnly><Layout><SmtpSettingsPage /></Layout></AdminOnly></CompanyRequired></Protected>} />
      <Route path="/backups" element={<Protected><CompanyRequired><AdminOnly><Layout><BackupsPage /></Layout></AdminOnly></CompanyRequired></Protected>} />
      <Route path="/shortcuts" element={<Protected><CompanyRequired><Layout><KeyboardShortcutsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <FYProvider>
        <ShortcutsProvider>
          <AppRoutes />
        </ShortcutsProvider>
      </FYProvider>
    </AuthProvider>
  );
}
