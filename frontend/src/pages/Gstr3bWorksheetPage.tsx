import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getApiErrorMessage, getBlobErrorMessage } from '../api/client';
import ScopeBar, { Metric } from '../components/ScopeBar';
import StatusToasts from '../components/StatusToasts';
import { downloadWorksheet, fetchWorksheet } from '../features/gstr3b/api';
import { documentLink } from '../features/gstr3b/links';
import { checkPeriod, defaultPeriod, worksheetPresets } from '../features/gstr3b/period';
import { gstr3bQueryKeys } from '../features/gstr3b/queryKeys';
import type {
  Gstr3bExportFormat,
  Gstr3bRow,
  Gstr3bSection,
  Gstr3bSetOff,
  Gstr3bSource,
  Gstr3bWarning,
  Gstr3bWorksheet,
} from '../features/gstr3b/types';
import formatCurrency from '../utils/formatting';
import { matchPreset, type DateRange } from '../utils/dateRanges';

/* GST is always rupees, whatever a company's display currency is set to. */
const CURRENCY = 'INR';

/* A B2C business can have hundreds of unregistered-buyer invoices in a month.
   The CSV lists them all; the page stays usable. */
const MAX_DOCUMENT_LINKS = 50;

/* Fixed in the page as well as sent by the API, so it is on screen before the
   figures load, and stays there if they fail to. */
const STANDING_NOTICE =
  'This is an estimate from your own books, for cross-checking only. It is not a filing and cannot be uploaded. Values auto-populated on the GST portal take precedence.';

const SOURCE_LABELS: Record<Gstr3bSource, string> = {
  from_books: 'From books',
  not_tracked: 'Not tracked',
};

function money(value: number | null) {
  return value === null ? '' : formatCurrency(value, CURRENCY);
}

function SourceBadge({ source }: { source: Gstr3bSource }) {
  return <span className={`worksheet-source worksheet-source--${source}`}>{SOURCE_LABELS[source]}</span>;
}

function WarningCard({ warning }: { warning: Gstr3bWarning }) {
  const { documents } = warning;
  const shown = documents.slice(0, MAX_DOCUMENT_LINKS);
  const hidden = documents.length - shown.length;

  return (
    <li className={`worksheet-warning worksheet-warning--${warning.severity}`}>
      <p className="worksheet-warning__title">
        {warning.title}
        {documents.length > 0 ? <span className="worksheet-warning__count"> ({documents.length})</span> : null}
      </p>
      <p className="worksheet-warning__message">{warning.message}</p>
      {documents.length > 0 ? (
        <details className="worksheet-warning__documents">
          <summary>
            {documents.length === 1 ? 'Show the document' : `Show ${documents.length} documents`}
          </summary>
          <ul>
            {shown.map((document, index) => (
              <li key={`${document.kind}-${document.id}-${index}`}>
                <Link to={documentLink(document)}>{document.number}</Link>
                {document.detail ? <span className="worksheet-warning__detail"> {document.detail}</span> : null}
              </li>
            ))}
          </ul>
          {hidden > 0 ? (
            <p className="worksheet-warning__detail">
              And {hidden} more. The CSV export lists every one.
            </p>
          ) : null}
        </details>
      ) : null}
    </li>
  );
}

function WarningsPanel({ warnings, knownLimits }: { warnings: Gstr3bWarning[]; knownLimits: string[] }) {
  return (
    <section className="content-grid content-grid--single" aria-label="Warnings">
      <article className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Read these first</p>
            <h2 className="nav-panel__title">Why this may not match the portal</h2>
          </div>
          <div className="status-chip">
            {warnings.length} {warnings.length === 1 ? 'warning' : 'warnings'}
          </div>
        </div>
        {warnings.length > 0 ? (
          <ul className="worksheet-warnings">
            {warnings.map((warning) => <WarningCard key={warning.code} warning={warning} />)}
          </ul>
        ) : (
          <p className="section-copy">
            Nothing in this period&apos;s documents needs a warning. The limits below still apply.
          </p>
        )}
        <div>
          <h3 className="worksheet-limits__title">Known limits</h3>
          <ul className="worksheet-limits">
            {knownLimits.map((limit) => <li key={limit}>{limit}</li>)}
          </ul>
        </div>
      </article>
    </section>
  );
}

function WorksheetRow({ row }: { row: Gstr3bRow }) {
  const tracked = row.source === 'from_books';
  return (
    <>
      <tr className={tracked ? undefined : 'worksheet-row--untracked'} data-row={row.key}>
        <td className="text-xs worksheet-row__table">{row.table}</td>
        <td>
          {row.label}
          {row.note ? <p className="worksheet-row__note">{row.note}</p> : null}
        </td>
        <td><SourceBadge source={row.source} /></td>
        {tracked ? (
          <>
            <td className="text-right">{money(row.taxable_value)}</td>
            <td className="text-right">{money(row.igst)}</td>
            <td className="text-right">{money(row.cgst)}</td>
            <td className="text-right">{money(row.sgst)}</td>
          </>
        ) : (
          <td colSpan={4} className="text-center muted-text text-xs">Not tracked</td>
        )}
      </tr>
      {row.components.map((component) => (
        <tr key={component.label} className="worksheet-row--component">
          <td />
          <td>{component.label}</td>
          <td />
          <td className="text-right">{money(component.taxable_value)}</td>
          <td className="text-right">{money(component.igst)}</td>
          <td className="text-right">{money(component.cgst)}</td>
          <td className="text-right">{money(component.sgst)}</td>
        </tr>
      ))}
    </>
  );
}

function SectionPanel({ section }: { section: Gstr3bSection }) {
  return (
    <section className="content-grid content-grid--single" data-section={section.key}>
      <article className="panel stack">
        <h2 className="nav-panel__title">{section.title}</h2>
        {section.note ? <p className="section-copy">{section.note}</p> : null}
        <div className="table-wrap worksheet-table-wrap">
          <table className="invoice-feed-table">
            <caption className="sr-only">{section.title}</caption>
            <thead>
              <tr>
                <th scope="col">Table</th>
                <th scope="col">Line</th>
                <th scope="col">Source</th>
                <th scope="col" className="text-right">Taxable value</th>
                <th scope="col" className="text-right">IGST</th>
                <th scope="col" className="text-right">CGST</th>
                <th scope="col" className="text-right">SGST</th>
              </tr>
            </thead>
            <tbody>
              {section.rows.map((row) => <WorksheetRow key={row.key} row={row} />)}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}

function SetOffPanel({ setoff }: { setoff: Gstr3bSetOff }) {
  return (
    <section className="content-grid content-grid--single" data-section="6.1">
      <article className="panel stack">
        <div className="panel__header">
          <h2 className="nav-panel__title">6.1 Payment of tax (estimate)</h2>
          <SourceBadge source={setoff.source} />
        </div>
        <p className="section-copy">{setoff.note}</p>
        <div className="table-wrap worksheet-table-wrap">
          <table className="invoice-feed-table">
            <caption className="sr-only">Table 6.1, payment of tax</caption>
            <thead>
              <tr>
                <th scope="col">Head</th>
                <th scope="col" className="text-right">Output tax</th>
                <th scope="col" className="text-right">Input credit</th>
                <th scope="col" className="text-right">Credit used</th>
                <th scope="col" className="text-right">Payable in cash</th>
                <th scope="col" className="text-right">Credit carried forward</th>
              </tr>
            </thead>
            <tbody>
              {setoff.lines.map((line) => (
                <tr key={line.head} data-head={line.head}>
                  <td>{line.head.toUpperCase()}</td>
                  <td className="text-right">{money(line.output_tax)}</td>
                  <td className="text-right">{money(line.input_credit)}</td>
                  <td className="text-right">{money(line.credit_used)}</td>
                  <td className="text-right">{money(line.payable)}</td>
                  <td className="text-right">{money(line.credit_carried_forward)}</td>
                </tr>
              ))}
              <tr className="worksheet-row--total">
                <td>Total</td>
                <td colSpan={3} />
                <td className="text-right">{money(setoff.total_payable)}</td>
                <td className="text-right">{money(setoff.total_credit_carried_forward)}</td>
              </tr>
              {setoff.rows.map((row) => (
                <tr key={row.key} className="worksheet-row--untracked" data-row={row.key}>
                  <td colSpan={2}>{row.label}</td>
                  <td><SourceBadge source={row.source} /></td>
                  <td colSpan={3} className="text-center muted-text text-xs">Not tracked</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}

/** The whole result, separate from the data fetching so it can be rendered in a test. */
export function Gstr3bWorksheetView({ worksheet }: { worksheet: Gstr3bWorksheet }) {
  return (
    <>
      <WarningsPanel warnings={worksheet.warnings} knownLimits={worksheet.known_limits} />
      {worksheet.sections.map((section) => <SectionPanel key={section.key} section={section} />)}
      <SetOffPanel setoff={worksheet.setoff} />
    </>
  );
}

export default function Gstr3bWorksheetPage() {
  const [period, setPeriod] = useState<DateRange>(() => defaultPeriod());
  const [downloading, setDownloading] = useState<Gstr3bExportFormat | null>(null);
  const [downloadError, setDownloadError] = useState('');

  const presets = useMemo(() => worksheetPresets(), []);
  const activePreset = matchPreset(presets, period);
  const check = checkPeriod(period);

  const query = useQuery({
    queryKey: gstr3bQueryKeys.worksheet(period.fromDate, period.toDate),
    queryFn: () => fetchWorksheet(period.fromDate, period.toDate),
    enabled: check.ok,
    // No keepPreviousData: last period's figures under this period's heading is
    // the one thing a return worksheet must never show.
  });
  const worksheet = check.ok ? query.data : undefined;

  async function handleDownload(format: Gstr3bExportFormat) {
    try {
      setDownloading(format);
      setDownloadError('');
      await downloadWorksheet(format, period.fromDate, period.toDate);
    } catch (err) {
      setDownloadError(await getBlobErrorMessage(err, `Unable to download the worksheet ${format.toUpperCase()}`));
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">GST reports</p>
          <h1 className="page-title">GSTR-3B worksheet</h1>
          <p className="section-copy">
            Compare what your books say with what the GST portal shows, before you file there.
          </p>
        </div>
        <Link className="button button--ghost button--small" to="/gstr1">
          GSTR-1 filing
        </Link>
      </section>

      <p className="worksheet-notice" role="note">
        <strong>Worksheet, not a return.</strong> {STANDING_NOTICE}
      </p>

      <StatusToasts
        error={downloadError}
        success=""
        onClearError={() => setDownloadError('')}
        onClearSuccess={() => {}}
      />

      <ScopeBar
        presets={(
          <div className="scope-presets" role="group" aria-label="Return period presets">
            {presets.map((preset) => (
              <button
                key={preset.key}
                type="button"
                className={`scope-preset${activePreset === preset.key ? ' scope-preset--on' : ''}`}
                aria-pressed={activePreset === preset.key}
                onClick={() => setPeriod({ fromDate: preset.fromDate, toDate: preset.toDate })}
              >
                {preset.label}
              </button>
            ))}
          </div>
        )}
        metrics={worksheet ? (
          <>
            <Metric label="Estimated cash payable" value={money(worksheet.setoff.total_payable)} />
            <Metric label="Credit carried forward" value={money(worksheet.setoff.total_credit_carried_forward)} />
            <Metric
              label="Warnings"
              value={worksheet.warnings.length}
              tone={worksheet.warnings.length > 0 ? 'danger' : undefined}
            />
          </>
        ) : undefined}
        actions={(
          <>
            {(['csv', 'pdf'] as const).map((format) => (
              <button
                key={format}
                type="button"
                className="button button--secondary button--small"
                onClick={() => { void handleDownload(format); }}
                disabled={downloading !== null || !worksheet}
              >
                {downloading === format ? 'Downloading…' : `Export ${format.toUpperCase()}`}
              </button>
            ))}
          </>
        )}
      >
        <div className="field">
          <label htmlFor="gstr3b-from">From</label>
          <input
            id="gstr3b-from"
            className="input"
            type="date"
            value={period.fromDate}
            onChange={(e) => setPeriod({ ...period, fromDate: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="gstr3b-to">To</label>
          <input
            id="gstr3b-to"
            className="input"
            type="date"
            value={period.toDate}
            onChange={(e) => setPeriod({ ...period, toDate: e.target.value })}
          />
        </div>
      </ScopeBar>

      {!check.ok ? <p className="field-warning" role="alert">{check.message}</p> : null}

      {check.ok && query.isError ? (
        <div className="empty-state" role="alert">
          {getApiErrorMessage(query.error, 'Unable to load the worksheet')}
        </div>
      ) : null}

      {check.ok && query.isPending ? <div className="empty-state">Loading worksheet…</div> : null}

      {worksheet ? (
        <>
          <p className="section-copy" data-testid="gstr3b-period">
            Showing {worksheet.period_label} ({worksheet.period_type === 'quarter' ? 'quarterly' : 'monthly'}).
          </p>
          <Gstr3bWorksheetView worksheet={worksheet} />
        </>
      ) : null}
    </div>
  );
}
