import { useEffect, useState } from 'react';
import { fetchDuesAgeing } from '../features/invoices/api';
import type { DuesAgeing } from '../types/api';
import { Metric } from './ScopeBar';
import formatCurrency from '../utils/formatting';

type DuesAgeingStripProps = {
  search: string;
  ledgerId?: number;
  currencyCode: string;
  /** Bump to refetch, e.g. after a payment is recorded. */
  refreshKey?: number;
};

/**
 * Pure tile rendering, kept separate from fetching so the figures can be
 * tested without a network round trip. The metric strip wraps, so the row
 * of tiles reflows on a narrow screen instead of overflowing.
 */
export function DuesAgeingTiles({ ageing, currencyCode }: { ageing: DuesAgeing; currencyCode: string }) {
  return (
    <div className="metric-strip">
      {ageing.buckets.map((bucket) => (
        <Metric
          key={bucket.key}
          label={bucket.label}
          tone={bucket.key === 'over_90' ? 'danger' : undefined}
          value={(
            <>
              {formatCurrency(bucket.total_remaining, currencyCode)}
              {' '}
              <span className="muted-text">({bucket.invoice_count})</span>
            </>
          )}
        />
      ))}
      <Metric
        label="Total outstanding"
        tone="accent"
        value={(
          <>
            {formatCurrency(ageing.total_remaining, currencyCode)}
            {' '}
            <span className="muted-text">({ageing.total_invoice_count})</span>
          </>
        )}
      />
    </div>
  );
}

export default function DuesAgeingStrip({ search, ledgerId, currencyCode, refreshKey = 0 }: DuesAgeingStripProps) {
  const [ageing, setAgeing] = useState<DuesAgeing | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        setFailed(false);
        const data = await fetchDuesAgeing({ search, ledgerId });
        if (!cancelled) {
          setAgeing(data);
        }
      } catch {
        if (!cancelled) {
          setFailed(true);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [search, ledgerId, refreshKey]);

  if (failed) {
    return null;
  }

  return (
    <section className="summary-box" aria-label="Receivables ageing summary">
      <p className="eyebrow">Receivables ageing</p>
      {loading || !ageing ? (
        <p className="muted-text">Loading ageing summary…</p>
      ) : (
        <>
          <DuesAgeingTiles ageing={ageing} currencyCode={currencyCode} />
          <p className="muted-text dues-ageing-note">
            As of {ageing.as_of_date}. These figures cover every unpaid invoice, whichever due window
            is chosen above{search || ledgerId ? ', narrowed only by your search and ledger' : ''}. Overdue tiles here can be lower than the dashboard overdue total:
            this page leaves out ledgers whose receivables are fully offset by what you owe them,
            while the dashboard counts every ledger.
          </p>
        </>
      )}
    </section>
  );
}
