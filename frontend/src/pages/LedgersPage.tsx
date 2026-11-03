import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  BadgeCheck,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  Globe,
  Landmark,
  Mail,
  MapPin,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import useDebouncedValue from '../hooks/useDebouncedValue';
import StatusToasts from '../components/StatusToasts';
import type { CompanyProfile, Ledger, PaginatedLedgers } from '../types/api';
import formatCurrency from '../utils/formatting';
import ConfirmDialog from '../components/ConfirmDialog';
import LedgerCardPhoneChips from '../components/LedgerCardPhoneChips';
import EmptyState from '../components/EmptyState';
import LoadingState from '../components/LoadingState';
import PageSizeSelect, { readStoredPageSize, storePageSize } from '../components/PageSizeSelect';
import SearchInput from '../components/SearchInput';
import { exportLedgersCsv } from './ledgers/exports';
import { buildLedgerListParams, parseLedgerListFilters } from '../utils/ledgerListFilters';

/** Monogram for the row avatar — first letters of the first two words. */
function ledgerInitials(name: string): string {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join('');
  return (letters || name.slice(0, 1) || '?').toUpperCase();
}

/**
 * Avatar tint, 1..6. Derived from the name rather than the id so the same
 * ledger keeps its colour across pages, searches and re-seeds — the colour is
 * decoration, but a *stable* colour is what makes a long list scannable.
 */
function ledgerTone(name: string): number {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) % 997;
  return (hash % 6) + 1;
}

/**
 * Which side a closing balance sits on, Tally-style: a positive (debit)
 * balance is receivable from the ledger, a negative one is payable to it.
 * Zero reads as debit so a settled ledger doesn't flip to "Cr".
 */
function balanceSide(balance: number): 'debit' | 'credit' {
  return balance < 0 ? 'credit' : 'debit';
}

export default function LedgersPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [deletingLedgerId, setDeletingLedgerId] = useState<number | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [pendingDeleteLedgerId, setPendingDeleteLedgerId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  // Search, sort and page live in the URL, like the Day Book page, so a
  // refresh, a back navigation or a shared link keeps the view. Deriving
  // them from the query string (rather than initialising state from it)
  // also makes back and forward update the list without a remount, and
  // keeps the search input a controlled input driven by the same value
  // the user just typed, so typing stays immediate with no cursor jump.
  const [searchParams, setSearchParams] = useSearchParams();
  const { search, sort, page } = parseLedgerListFilters(searchParams);

  // Replace, never push: typing must not stack a history entry per
  // keystroke, and a filter change should not trap Back behind every
  // nudge either. Changing search or sort resets to page 1, as before.
  function updateLedgerFilters(patch: { search?: string; sort?: string; page?: number }) {
    setSearchParams(
      buildLedgerListParams({ search, sort, page, ...patch }, searchParams),
      { replace: true },
    );
  }
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [pageSize, setPageSize] = useState(() => readStoredPageSize('ledgers-page-size'));
  const [exporting, setExporting] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const debouncedSearch = useDebouncedValue(search, 300);

  useEffect(() => {
    const state = location.state as { success?: string } | null;
    if (state?.success) {
      setSuccess(state.success);
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        setError('');
        const res = await api.get<PaginatedLedgers>('/ledgers/', {
          params: { page, page_size: pageSize, search: debouncedSearch, sort },
        });
        if (cancelled) return;
        setLedgers(res.data.items);
        setTotal(res.data.total);
        setTotalPages(res.data.total_pages);
      } catch (err) {
        if (cancelled) return;
        setError(getApiErrorMessage(err, 'Unable to load ledgers'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [page, debouncedSearch, sort, pageSize, reloadKey]);

  // Exports every ledger the current search and sort select, not just the
  // visible page: the export pages the list endpoint itself (see ledgers/exports).
  async function handleExportCsv() {
    try {
      setExporting(true);
      setError('');
      await exportLedgersCsv(search, sort);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to export ledgers as CSV'));
    } finally {
      setExporting(false);
    }
  }

  function handlePageSizeChange(nextPageSize: number) {
    storePageSize('ledgers-page-size', nextPageSize);
    setPageSize(nextPageSize);
    updateLedgerFilters({ page: 1 });
  }

  // Currency is only needed to render balances; a failure here leaves the
  // default in place rather than blocking the registry.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await api.get<CompanyProfile>('/company/');
        if (!cancelled) setCompany(res.data);
      } catch {
        /* keep the default currency */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function handleDeleteLedger(ledgerId: number) {
    setPendingDeleteLedgerId(ledgerId);
    setShowDeleteDialog(true);
  }

  function cancelDeleteLedger() {
    setShowDeleteDialog(false);
    setPendingDeleteLedgerId(null);
  }

  async function confirmDeleteLedger() {
    if (pendingDeleteLedgerId === null) return;
    setShowDeleteDialog(false);

    try {
      setDeletingLedgerId(pendingDeleteLedgerId);
      setError('');
      setSuccess('');
      await api.delete(`/ledgers/${pendingDeleteLedgerId}`);
      setLedgers((current) => current.filter((l) => l.id !== pendingDeleteLedgerId));
      setTotal((t) => t - 1);
      setSuccess('Ledger deleted successfully.');
      setReloadKey((k) => k + 1);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to delete ledger'));
    } finally {
      setDeletingLedgerId(null);
      setPendingDeleteLedgerId(null);
    }
  }

  const activeCurrencyCode = company?.currency_code || 'INR';
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, total);

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Ledgers</p>
          <h1 className="page-title">Ledger master</h1>
          <p className="section-copy">A minimal Tally-style ledger registry with period-wise view of sales and purchase postings.</p>
        </div>
        <div className="page-hero__actions">
          <div className="status-chip">{total} ledgers listed</div>
          <button
            type="button"
            className="button button--secondary"
            disabled={exporting || total === 0}
            onClick={() => void handleExportCsv()}
            title="Export ledgers as CSV"
            aria-label="Export ledgers as CSV"
          >
            <Download size={16} />
            {exporting ? 'Exporting…' : 'Export CSV'}
          </button>
          <button
            className="button button--primary"
            onClick={() => navigate('/ledgers/new')}
            title="Create ledger"
            aria-label="Create ledger"
          >
            <Plus size={16} />
            Create ledger
          </button>
        </div>
      </section>

      <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Registry</p>
              <h2 className="nav-panel__title">All ledgers</h2>
            </div>
          </div>

          <div className="ledger-toolbar">
            <SearchInput
              id="ledger-search"
              wrapperClassName="ledger-search"
              inputClassName="input ledger-search__input"
              iconClassName="ledger-search__icon"
              clearClassName="ledger-search__clear"
              label="Search ledgers by name"
              placeholder="Search ledgers by name, GST or contact..."
              value={search}
              onChange={(value) => {
                updateLedgerFilters({ search: value, page: 1 });
              }}
            />
            <div>
              <label htmlFor="ledger-sort" className="sr-only">
                Sort ledgers
              </label>
              <select
                id="ledger-sort"
                className="input"
                aria-label="Sort ledgers"
                value={sort}
                onChange={(e) => {
                  updateLedgerFilters({ sort: e.target.value, page: 1 });
                }}
              >
                <option value="name">Name A to Z</option>
                <option value="-name">Name Z to A</option>
                <option value="newest">Newest first</option>
                <option value="balance_desc">Highest balance first</option>
              </select>
            </div>
            {!loading && total > 0 ? (
              <p className="ledger-toolbar__count">
                Showing <strong>{rangeStart}–{rangeEnd}</strong> of {total}
              </p>
            ) : null}
          </div>

          <div className="table-list ledger-list">
            {/* Standardized empty states for loading, empty registry, and search results */}
            {loading ? (
              <>
                <LoadingState message="Loading ledgers..." />
                {/* Skeleton rows keep the list's shape while it loads, so the panel
                    does not collapse and snap back once the data lands. */}
                <div className="ledger-skeletons" aria-hidden="true">
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="ledger-skeleton">
                      <span className="ledger-skeleton__avatar" />
                      <div className="ledger-skeleton__lines">
                        <span className="ledger-skeleton__line ledger-skeleton__line--title" />
                        <span className="ledger-skeleton__line" />
                        <span className="ledger-skeleton__line ledger-skeleton__line--short" />
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : null}
            {!loading && ledgers.length === 0 && !search ? (
              <EmptyState
                message="No ledgers registered yet. Create your first ledger to start tracking buyers and suppliers."
                action={{ label: 'Create First Ledger', onClick: () => navigate('/ledgers/new') }}
              />
            ) : null}
            {!loading && ledgers.length === 0 && search ? (
              <EmptyState message="No ledgers match your search." />
            ) : null}
            {!loading
              ? ledgers.map((ledger) => {
                  const hasBank = Boolean(ledger.bank_name || ledger.account_number || ledger.ifsc_code);
                  return (
                    <article key={ledger.id} className="table-row ledger-card">
                      <span className={`ledger-card__avatar ledger-card__avatar--${ledgerTone(ledger.name)}`} aria-hidden="true">
                        {ledgerInitials(ledger.name)}
                      </span>

                      <div className="table-row__meta ledger-card__body">
                        <div className="ledger-card__headline">
                          <button
                            type="button"
                            className="ledger-card__name"
                            onClick={() => navigate(`/ledgers/${ledger.id}`)}
                            title={`Open ledger ${ledger.name}`}
                          >
                            {ledger.name}
                          </button>
                          {ledger.gst ? (
                            <span className="ledger-chip ledger-chip--gst" title={`GSTIN ${ledger.gst}`}>
                              <BadgeCheck size={13} />
                              {ledger.gst}
                            </span>
                          ) : null}
                        </div>

                        {ledger.phone_number || ledger.email || ledger.website ? (
                          <div className="ledger-card__contacts">
                            {ledger.phone_number ? (
                              <LedgerCardPhoneChips phone={ledger.phone_number} />
                            ) : null}
                            {ledger.email ? (
                              <span className="ledger-chip">
                                <Mail size={13} />
                                {ledger.email}
                              </span>
                            ) : null}
                            {ledger.website ? (
                              <span className="ledger-chip">
                                <Globe size={13} />
                                {ledger.website}
                              </span>
                            ) : null}
                          </div>
                        ) : null}

                        {ledger.address ? (
                          <p className="ledger-card__address">
                            <MapPin size={13} aria-hidden="true" />
                            <span>{ledger.address}</span>
                          </p>
                        ) : null}

                        {hasBank ? (
                          <div className="ledger-card__bank">
                            <Landmark size={14} aria-hidden="true" />
                            <dl className="ledger-card__bank-facts">
                              {ledger.bank_name ? (
                                <div>
                                  <dt>Bank</dt>
                                  <dd>
                                    {ledger.bank_name}
                                    {ledger.branch_name ? ` · ${ledger.branch_name}` : ''}
                                  </dd>
                                </div>
                              ) : null}
                              {ledger.account_number ? (
                                <div>
                                  <dt>A/C</dt>
                                  <dd>{ledger.account_number}</dd>
                                </div>
                              ) : null}
                              {ledger.ifsc_code ? (
                                <div>
                                  <dt>IFSC</dt>
                                  <dd>{ledger.ifsc_code}</dd>
                                </div>
                              ) : null}
                            </dl>
                          </div>
                        ) : null}
                      </div>

                      <div className="ledger-card__aside">
                        <span className="ledger-card__id">#{ledger.id}</span>
                        {ledger.balance != null ? (
                          <div
                            className={`ledger-card__balance ledger-card__balance--${balanceSide(ledger.balance)}`}
                            title={`Closing balance ${formatCurrency(Math.abs(ledger.balance), activeCurrencyCode)} ${
                              balanceSide(ledger.balance) === 'debit' ? 'debit' : 'credit'
                            }`}
                          >
                            <span className="ledger-card__balance-label">Balance</span>
                            <span className="ledger-card__balance-value">
                              {formatCurrency(Math.abs(ledger.balance), activeCurrencyCode)}
                              <span className="ledger-card__balance-side">
                                {balanceSide(ledger.balance) === 'debit' ? 'Dr' : 'Cr'}
                              </span>
                            </span>
                          </div>
                        ) : null}
                        <div className="table-row__actions ledger-card__actions">
                          <button
                            type="button"
                            className="button button--ghost button--icon"
                            onClick={() => navigate(`/ledgers/${ledger.id}`)}
                            title={`View ledger ${ledger.name}`}
                            aria-label={`View ledger ${ledger.name}`}
                          >
                            <Eye size={16} />
                          </button>
                          <button
                            type="button"
                            className="button button--ghost button--icon"
                            onClick={() => navigate(`/ledgers/${ledger.id}/edit`)}
                            title={`Edit ledger ${ledger.name}`}
                            aria-label={`Edit ledger ${ledger.name}`}
                          >
                            <Pencil size={16} />
                          </button>
                          <button
                            type="button"
                            className="button button--danger button--icon"
                            onClick={() => handleDeleteLedger(ledger.id)}
                            disabled={deletingLedgerId === ledger.id}
                            title={`Delete ledger ${ledger.name}`}
                            aria-label={`Delete ledger ${ledger.name}`}
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })
              : null}
          </div>

          {total > 0 ? (
            <div className="ledger-pagination">
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={page <= 1}
                onClick={() => updateLedgerFilters({ page: page - 1 })}
                title="Previous page"
                aria-label="Previous page"
              >
                <ChevronLeft size={15} />
                Previous
              </button>
              <span className="ledger-pagination__status">
                Page <strong>{page}</strong> of {totalPages}
              </span>
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={page >= totalPages}
                onClick={() => updateLedgerFilters({ page: page + 1 })}
                title="Next page"
                aria-label="Next page"
              >
                Next
                <ChevronRight size={15} />
              </button>
              <PageSizeSelect id="ledgers-page-size" value={pageSize} onChange={handlePageSizeChange} />
            </div>
          ) : null}
        </article>
      </section>

      {showDeleteDialog ? (
        <ConfirmDialog
          message={`Are you sure you want to delete ledger #${pendingDeleteLedgerId}?`}
          title="Delete ledger"
          confirmText="Delete"
          cancelText="Cancel"
          danger={true}
          onConfirm={() => void confirmDeleteLedger()}
          onCancel={cancelDeleteLedger}
        />
      ) : null}
    </div>
  );
}
