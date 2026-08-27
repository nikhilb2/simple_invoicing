import { useEffect, useState } from 'react';
import { Search, X } from 'lucide-react';
import { getApiErrorMessage } from '../../api/client';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import useDebouncedValue from '../../hooks/useDebouncedValue';
import { fetchAvailableSerials } from '../../features/serials/api';
import type { Serial } from '../../features/serials/types';
import type { CatalogueRow } from './types';

const PAGE_SIZE = 50;

/**
 * The serial history for one product.
 *
 * On the old grid this lived inside a `colSpan` cell within the table's own
 * horizontal scroller, so it slid sideways with the columns and only one row
 * could be expanded at a time. As a dialog it keeps its own space, and closing
 * it does not disturb the list underneath.
 */

type SerialHistoryDrawerProps = {
  row: CatalogueRow;
  onClose: () => void;
  /** Pre-fills the filter when arriving from a scanned-code deep link. */
  initialSearch?: string;
};

function formatDate(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export default function SerialHistoryDrawer({
  row,
  onClose,
  initialSearch = '',
}: SerialHistoryDrawerProps) {
  const [search, setSearch] = useState(initialSearch);
  const [serials, setSerials] = useState<Serial[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const debouncedSearch = useDebouncedValue(search, 300);

  useEscapeClose(onClose);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');

    fetchAvailableSerials({
      productId: row.id,
      search: debouncedSearch,
      page,
      pageSize: PAGE_SIZE,
      // The full history, not just sellable units — this drawer answers
      // "where did this one go?", which needs the sold ones too.
      status: null,
    })
      .then((response) => {
        if (cancelled) return;
        setSerials(response.items);
        setTotal(response.total);
      })
      .catch((err) => {
        if (cancelled) return;
        setSerials([]);
        setTotal(0);
        setError(getApiErrorMessage(err, 'Unable to load serial numbers'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [row.id, debouncedSearch, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const titleId = 'serial-history-title';

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-panel modal-panel--serial-history"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="panel__header">
          <div>
            <p className="eyebrow">Serial numbers</p>
            <h2 className="nav-panel__title" id={titleId}>
              {row.name}
            </h2>
          </div>
          <button
            type="button"
            className="button button--ghost button--icon"
            onClick={onClose}
            title="Close"
            aria-label="Close serial numbers"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="catalogue-search">
          <Search size={16} className="catalogue-search__icon" aria-hidden="true" />
          <label className="sr-only" htmlFor="serial-history-search">
            Search serial numbers
          </label>
          <input
            id="serial-history-search"
            className="input catalogue-search__input"
            type="search"
            placeholder="Search serials..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {search ? (
            <button
              type="button"
              className="catalogue-search__clear"
              onClick={() => setSearch('')}
              title="Clear search"
              aria-label="Clear serial search"
            >
              <X size={14} aria-hidden="true" />
            </button>
          ) : null}
        </div>

        {error ? (
          <p className="serial-history__error" role="alert">
            {error}
          </p>
        ) : null}

        {loading ? (
          <p className="muted-text" role="status">
            Loading serial numbers...
          </p>
        ) : null}

        {!loading && !error && serials.length === 0 ? (
          <p className="muted-text">
            {search ? 'No serials match that search.' : 'No serials recorded for this product yet.'}
          </p>
        ) : null}

        {!loading && serials.length > 0 ? (
          <ul className="serial-history__list">
            {serials.map((serial) => {
              const inRef = serial.purchase_invoice;
              const outRef = serial.sales_invoice;
              return (
                <li key={serial.id} className="serial-history__row">
                  <span className="serial-history__number">{serial.serial_number}</span>
                  <span
                    className={`status-chip${serial.status === 'sold' ? ' status-chip--paused' : ' status-chip--success'}`}
                  >
                    {serial.status === 'sold' ? 'Sold' : 'In stock'}
                  </span>
                  <dl className="serial-history__movement">
                    {inRef ? (
                      <div>
                        <dt>In</dt>
                        <dd>
                          {inRef.invoice_number ?? `#${inRef.id}`}
                          {formatDate(inRef.invoice_date) ? ` · ${formatDate(inRef.invoice_date)}` : ''}
                        </dd>
                      </div>
                    ) : null}
                    {outRef ? (
                      <div>
                        <dt>Out</dt>
                        <dd>
                          {outRef.invoice_number ?? `#${outRef.id}`}
                          {formatDate(outRef.invoice_date)
                            ? ` · ${formatDate(outRef.invoice_date)}`
                            : ''}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                </li>
              );
            })}
          </ul>
        ) : null}

        {!loading && total > PAGE_SIZE ? (
          <div className="ledger-pagination">
            <button
              type="button"
              className="button button--ghost button--small"
              disabled={page <= 1}
              onClick={() => setPage((current) => current - 1)}
            >
              Previous
            </button>
            <span className="ledger-pagination__status">
              <strong>{(page - 1) * PAGE_SIZE + 1}</strong>–
              {Math.min(page * PAGE_SIZE, total)} of {total}
            </span>
            <button
              type="button"
              className="button button--ghost button--small"
              disabled={page >= totalPages}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
