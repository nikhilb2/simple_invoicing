import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Check, X } from 'lucide-react';
import api from '../api/client';
import { canStartTour, INVOICE_PATH } from '../features/firstInvoiceTour/tourSteps';
import { useAuthStore } from '../store/useAuthStore';
import { useFirstInvoiceTourStore } from '../store/useFirstInvoiceTourStore';
import type { CompanyAccount, DashboardMetrics, PaginatedLedgers } from '../types/api';
import {
  activeCompanyId,
  getStartedStatus,
  isGetStartedComplete,
  readGetStartedDismissed,
  shouldRunGetStarted,
  writeGetStartedDismissed,
  type GetStartedFacts,
  type GetStartedStatus,
} from '../utils/getStarted';

const QUICK_START_URL = 'https://guide.simpleinvoicings.com/getting-started/';

const STEPS: Array<{
  id: keyof GetStartedStatus;
  title: string;
  copy: string;
  to: string;
  action: string;
  optional?: boolean;
}> = [
  { id: 'customer', title: 'Add a customer', copy: 'Who you sell to.', to: '/ledgers/new', action: 'Add customer' },
  {
    id: 'product',
    title: 'Add a product with opening stock',
    copy: 'What you sell, and how many you have now.',
    to: '/catalogue',
    action: 'Open catalogue',
  },
  { id: 'invoice', title: 'Create your first invoice', copy: 'Needs a customer and a product.', to: '/invoices', action: 'Create invoice' },
  {
    id: 'bank',
    title: 'Add your bank details',
    copy: 'So they print on your invoices.',
    to: '/cash-bank/accounts',
    action: 'Add bank account',
    optional: true,
  },
];

type Props = {
  status: GetStartedStatus;
  onDismiss: () => void;
  /** Starts the walkthrough. Left out for people who could not finish it. */
  onStartTour?: () => void;
};

/** Presentational half: renders nothing once the required steps are done. */
export function GetStartedCard({ status, onDismiss, onStartTour }: Props) {
  if (isGetStartedComplete(status)) return null;

  return (
    <section className="panel stack get-started" aria-labelledby="get-started-title">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Get started</p>
          <h2 className="nav-panel__title" id="get-started-title">Set up your first invoice</h2>
        </div>
        <button
          type="button"
          className="button button--ghost button--icon"
          onClick={onDismiss}
          title="Hide this checklist"
          aria-label="Hide this checklist"
        >
          <X size={16} />
        </button>
      </div>

      <ol className="get-started__list">
        {STEPS.map((step) => {
          const done = status[step.id];
          return (
            <li key={step.id} className={`get-started__step${done ? ' get-started__step--done' : ''}`}>
              <span className="get-started__mark" aria-hidden="true">{done ? <Check size={14} /> : null}</span>
              <div className="get-started__text">
                <strong>
                  {step.title}
                  {step.optional ? <span className="get-started__optional"> (optional)</span> : null}
                </strong>
                <span className="table-subtext">{done ? 'Done' : step.copy}</span>
              </div>
              {done ? null : (
                <Link to={step.to} className="button button--secondary button--small">{step.action}</Link>
              )}
            </li>
          );
        })}
      </ol>

      <p className="table-subtext">
        New to this?{' '}
        {onStartTour ? (
          <>
            <button type="button" className="link-button" onClick={onStartTour}>Walk me through it</button>
            {' or '}
          </>
        ) : null}
        <a href={QUICK_START_URL} target="_blank" rel="noreferrer">{onStartTour ? 'read the Quick start' : 'Read the Quick start'}</a>
      </p>
    </section>
  );
}

/**
 * Looks up what the dashboard metrics cannot say (customers, bank accounts) and
 * only while the card can still appear. Companies that already have invoices, or
 * dismissed it, make no extra requests.
 */
export default function GetStartedChecklist({ metrics }: { metrics: DashboardMetrics | null }) {
  const [companyId] = useState(activeCompanyId);
  const [dismissed, setDismissed] = useState(() => readGetStartedDismissed(companyId));
  const [facts, setFacts] = useState<GetStartedFacts | null>(null);
  const run = shouldRunGetStarted(metrics, dismissed);
  const companyRole = useAuthStore((state) => state.companyRole);
  const startTour = useFirstInvoiceTourStore((state) => state.start);
  const navigate = useNavigate();

  useEffect(() => {
    if (!run) return;
    let active = true;
    // A failed lookup leaves the step unticked rather than hiding the card.
    const count = (req: Promise<number>) => req.catch(() => null);
    void Promise.all([
      count(api.get<PaginatedLedgers>('/ledgers/', { params: { page_size: 1 } }).then((r) => r.data.total)),
      count(api.get<CompanyAccount[]>('/company-accounts/').then((r) => r.data.filter((a) => a.account_type === 'bank').length)),
    ]).then(([ledgerCount, bankAccountCount]) => {
      if (active) setFacts({ ledgerCount, bankAccountCount });
    });
    return () => {
      active = false;
    };
  }, [run]);

  if (!run || !metrics || !facts) return null;

  return (
    <GetStartedCard
      status={getStartedStatus(metrics, facts)}
      onStartTour={
        canStartTour(companyRole)
          ? () => {
              startTour();
              navigate(INVOICE_PATH);
            }
          : undefined
      }
      onDismiss={() => {
        writeGetStartedDismissed(companyId);
        setDismissed(true);
      }}
    />
  );
}
