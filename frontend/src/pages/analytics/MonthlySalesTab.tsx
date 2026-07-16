import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { getBlobErrorMessage } from '../../api/client';
import StatusToasts from '../../components/StatusToasts';
import { downloadMonthlySalesCsv, fetchMonthlySales } from '../../features/analytics/api';
import { analyticsQueryKeys } from '../../features/analytics/queryKeys';
import type { AnalyticsFilters } from '../../features/analytics/types';
import formatCurrency from '../../utils/formatting';
import MonthlySalesChart from './charts/MonthlySalesChart';

export default function MonthlySalesTab({ filters }: { filters: AnalyticsFilters }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');

  const query = useQuery({
    queryKey: analyticsQueryKeys.monthlySales(filters),
    queryFn: () => fetchMonthlySales(filters),
    // Keeps the previous report on screen while a filter change loads, so the
    // chart doesn't flash empty.
    placeholderData: keepPreviousData,
  });

  async function handleDownload() {
    if (!query.data) return;
    try {
      setDownloading(true);
      setError('');
      await downloadMonthlySalesCsv(filters, {
        from: query.data.period.from_date,
        to: query.data.period.to_date,
      });
    } catch (err) {
      // Blob-mode errors arrive as an unreadable Blob; this helper unwraps them.
      setError(await getBlobErrorMessage(err, 'Unable to download the CSV'));
    } finally {
      setDownloading(false);
    }
  }

  if (query.isLoading) {
    return <div className="empty-state">Loading month-wise sales…</div>;
  }

  if (query.error || !query.data) {
    return <div className="empty-state">Unable to load month-wise sales.</div>;
  }

  const { rows, totals, currency_code: currency } = query.data;

  return (
    <div className="analytics-tab">
      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <div className="analytics-tab__actions">
        <button className="button button--ghost" onClick={handleDownload} disabled={downloading}>
          <Download size={16} aria-hidden="true" />
          {downloading ? 'Preparing…' : 'Export CSV'}
        </button>
      </div>

      {totals.invoice_count === 0 ? (
        <div className="empty-state">No invoices in this period.</div>
      ) : (
        <>
          <MonthlySalesChart rows={rows} currencyCode={currency} />

          <div className="analytics-table-scroll">
            <table className="invoice-feed-table">
              <thead>
                <tr>
                  <th>Month</th>
                  <th className="text-right">Invoices</th>
                  <th className="text-right">Total Sales</th>
                  <th className="text-right">Taxable Value</th>
                  <th className="text-right">GST Collected</th>
                  <th className="text-right">Discount Given</th>
                  <th className="text-right">Avg Invoice Value</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.month}>
                    <td>{row.label}</td>
                    <td className="text-right">{row.invoice_count}</td>
                    <td className="text-right">{formatCurrency(row.total_sales, currency)}</td>
                    <td className="text-right">{formatCurrency(row.taxable_value, currency)}</td>
                    <td className="text-right">{formatCurrency(row.gst_collected, currency)}</td>
                    <td className="text-right">{formatCurrency(row.discount_given, currency)}</td>
                    <td className="text-right">{formatCurrency(row.average_invoice_value, currency)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>Totals</th>
                  <th className="text-right">{totals.invoice_count}</th>
                  <th className="text-right">{formatCurrency(totals.total_sales, currency)}</th>
                  <th className="text-right">{formatCurrency(totals.taxable_value, currency)}</th>
                  <th className="text-right">{formatCurrency(totals.gst_collected, currency)}</th>
                  <th className="text-right">{formatCurrency(totals.discount_given, currency)}</th>
                  <th className="text-right">{formatCurrency(totals.average_invoice_value, currency)}</th>
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
