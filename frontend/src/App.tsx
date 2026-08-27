import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes, useLocation, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { MotionConfig } from 'framer-motion';
import { AuthProvider, useAuth } from './context/AuthContext';
import { FYProvider } from './context/FYContext';
import { ShortcutsProvider } from './context/ShortcutsContext';
import api from './api/client';
import type { CompanyProfile } from './types/api';
import { isCompanyConfigured } from './utils/companySetup';
import { loginPathWithNext, sanitizeNextPath } from './utils/nextPath';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import CataloguePage from './pages/CataloguePage';
import ProduceItemsPage from './pages/ProduceItemsPage';
import InvoicesPage from './pages/InvoicesPage';
import InvoiceDuesPage from './pages/InvoiceDuesPage';
import InvoicesAdvancedView from './pages/InvoicesAdvancedView';
import CreditNotesPage from './pages/CreditNotesPage';
import LedgersPage from './pages/LedgersPage';
import LedgerCreatePage from './pages/LedgerCreatePage';
import LedgerViewPage from './pages/LedgerViewPage';
import DayBookPage from './pages/DayBookPage';
import TaxLedgerPage from './pages/TaxLedgerPage';
import CashBankPage from './pages/CashBankPage';
import CashBankAccountsPage from './pages/CashBankAccountsPage';
import CompanyPage from './pages/CompanyPage';
import SmtpSettingsPage from './pages/SmtpSettingsPage';
import BackupsPage from './pages/BackupsPage';
import KeyboardShortcutsPage from './pages/KeyboardShortcutsPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import ApiKeysPage from './pages/ApiKeysPage';
import ConnectedAppsPage from './pages/settings/ConnectedAppsPage';
import OAuthConsentPage from './pages/oauth/OAuthConsentPage';
import EmailHistoryPage from './pages/EmailHistoryPage';
import MyListingsPage from './pages/marketplace/MyListingsPage';
import MarketplaceOrdersPage from './pages/marketplace/MarketplaceOrdersPage';
import MarketplaceSettingsPage from './pages/marketplace/MarketplaceSettingsPage';
import SettingsLayout from './pages/settings/SettingsLayout';
import SettingsOverviewPage from './pages/settings/SettingsOverviewPage';
import { LEGACY_REDIRECTS } from './config/navigation';
import Layout from './components/Layout';

// Lazily loaded: this is the only route that pulls in recharts (~100kb gz), and
// every other route here is imported eagerly — they shouldn't pay for it.
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));

// Browse is the marketplace's heaviest page and the one an instance with no
// connection never opens, so it isn't in the main bundle either.
const MarketplaceBrowsePage = lazy(() => import('./pages/marketplace/MarketplaceBrowsePage'));

/**
 * Requires a session, and remembers where the visitor was going.
 *
 * The return path is not a nicety: an MCP client sends the user straight to
 * /oauth/consent?request_id=…, and before this carried `?next=` they signed in
 * and landed on the dashboard with the pending authorization request stranded.
 * `sanitizeNextPath` on the way back is what keeps that from being an open
 * redirect — see utils/nextPath.ts.
 */
function Protected({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to={loginPathWithNext(`${location.pathname}${location.search}`)} replace />;
  }

  return children;
}

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [searchParams] = useSearchParams();

  if (isAuthenticated) {
    return <Navigate to={sanitizeNextPath(searchParams.get('next'))} replace />;
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
    return <Navigate to="/settings/company?setup=required" replace />;
  }

  return children;
}

/**
 * A settings page, framed by the settings sub-navigation.
 *
 * The guard combination is passed as props rather than nested by hand at each
 * call site: nine settings routes composing up to four guards each is where the
 * inline style stopped paying for itself. `requireCompany` is false for exactly
 * one page — /settings/company is where CompanyRequired *sends* people, so
 * guarding it with CompanyRequired would be a redirect loop.
 */
function SettingsRoute({
  admin = false,
  requireCompany = true,
  children,
}: {
  admin?: boolean;
  requireCompany?: boolean;
  children: React.ReactNode;
}) {
  let node = (
    <Layout>
      <SettingsLayout>{children}</SettingsLayout>
    </Layout>
  );
  if (admin) node = <AdminOnly>{node}</AdminOnly>;
  if (requireCompany) node = <CompanyRequired>{node}</CompanyRequired>;
  return <Protected>{node}</Protected>;
}

/** A moved route. Keeps the query string so ?setup=required survives the hop. */
function LegacyRedirect({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={`${to}${search}${hash}`} replace />;
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
      {/* Mid-flow from an external MCP client. Deliberately outside Layout and
          CompanyRequired: the visitor is answering one question, and a company
          setup redirect here would strand the pending authorization request. */}
      <Route path="/oauth/consent" element={<Protected><OAuthConsentPage /></Protected>} />
      <Route path="/" element={<Protected><CompanyRequired><Layout><DashboardPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/catalogue" element={<Protected><CompanyRequired><Layout><CataloguePage /></Layout></CompanyRequired></Protected>} />
      {/* The three pages the catalogue replaces. /products-inventory is the
          target every MCP product and serial citation already points at, so the
          redirect has to carry ?product_id= / ?serial= across with it. */}
      <Route path="/products" element={<LegacyRedirect to="/catalogue" />} />
      <Route path="/inventory" element={<LegacyRedirect to="/catalogue" />} />
      <Route path="/products-inventory" element={<LegacyRedirect to="/catalogue" />} />
      <Route path="/produce-items" element={<Protected><CompanyRequired><Layout><ProduceItemsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers" element={<Protected><CompanyRequired><Layout><LedgersPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/new" element={<Protected><CompanyRequired><Layout><LedgerCreatePage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/:id" element={<Protected><CompanyRequired><Layout><LedgerViewPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/ledgers/:id/edit" element={<Protected><CompanyRequired><Layout><LedgerCreatePage /></Layout></CompanyRequired></Protected>} />
      <Route path="/analytics" element={<Protected><CompanyRequired><Layout><Suspense fallback={<div className="empty-state">Loading analytics…</div>}><AnalyticsPage /></Suspense></Layout></CompanyRequired></Protected>} />
      <Route path="/day-book" element={<Protected><CompanyRequired><Layout><DayBookPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/tax-ledger" element={<Protected><CompanyRequired><Layout><TaxLedgerPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/cash-bank" element={<Protected><CompanyRequired><Layout><CashBankPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/cash-bank/accounts" element={<Protected><CompanyRequired><Layout><CashBankAccountsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/invoices" element={<Protected><CompanyRequired><Layout><InvoicesPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/invoice-dues" element={<Protected><CompanyRequired><Layout><InvoiceDuesPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/invoices-view" element={<Protected><CompanyRequired><Layout><InvoicesAdvancedView /></Layout></CompanyRequired></Protected>} />
      <Route path="/credit-notes" element={<Protected><CompanyRequired><Layout><CreditNotesPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/marketplace" element={<Protected><CompanyRequired><Layout><Suspense fallback={<div className="empty-state">Loading marketplace…</div>}><MarketplaceBrowsePage /></Suspense></Layout></CompanyRequired></Protected>} />
      <Route path="/marketplace/listings" element={<Protected><CompanyRequired><Layout><MyListingsPage /></Layout></CompanyRequired></Protected>} />
      <Route path="/marketplace/orders" element={<Protected><CompanyRequired><Layout><MarketplaceOrdersPage /></Layout></CompanyRequired></Protected>} />
      {/* ── Settings ───────────────────────────────────────────────── */}
      <Route path="/settings" element={<SettingsRoute requireCompany={false}><SettingsOverviewPage /></SettingsRoute>} />
      <Route path="/settings/company" element={<SettingsRoute requireCompany={false}><CompanyPage /></SettingsRoute>} />
      <Route path="/settings/marketplace" element={<SettingsRoute admin><MarketplaceSettingsPage /></SettingsRoute>} />
      <Route path="/settings/email" element={<SettingsRoute admin><SmtpSettingsPage /></SettingsRoute>} />
      <Route path="/settings/email-history" element={<SettingsRoute admin><EmailHistoryPage /></SettingsRoute>} />
      <Route path="/settings/security" element={<SettingsRoute><ChangePasswordPage /></SettingsRoute>} />
      <Route path="/settings/shortcuts" element={<SettingsRoute><KeyboardShortcutsPage /></SettingsRoute>} />
      <Route path="/settings/api-keys" element={<SettingsRoute admin><ApiKeysPage /></SettingsRoute>} />
      {/* Per-user, not admin-only: a user manages the connectors they themselves consented to. */}
      <Route path="/settings/connected-apps" element={<SettingsRoute><ConnectedAppsPage /></SettingsRoute>} />
      <Route path="/settings/backups" element={<SettingsRoute admin><BackupsPage /></SettingsRoute>} />

      {/* Where those pages used to live. */}
      {Object.entries(LEGACY_REDIRECTS).map(([from, to]) => (
        <Route key={from} path={from} element={<LegacyRedirect to={to} />} />
      ))}

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    /* The page transition in Layout and the dropdown animations moved
       regardless of the OS "reduce motion" setting — the stylesheet's
       prefers-reduced-motion block cannot reach a framer-motion animation
       because those are driven from JS. `reducedMotion="user"` makes every
       motion element in the tree drop its transform and layout animation when
       the user has asked for that, keeping only opacity. */
    <MotionConfig reducedMotion="user">
      <AuthProvider>
        <FYProvider>
          <ShortcutsProvider>
            <AppRoutes />
          </ShortcutsProvider>
        </FYProvider>
      </AuthProvider>
    </MotionConfig>
  );
}
