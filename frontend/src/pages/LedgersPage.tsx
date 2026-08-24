import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  BadgeCheck,
  ChevronLeft,
  ChevronRight,
  Eye,
  Globe,
  Landmark,
  Mail,
  MapPin,
  Pencil,
  Phone,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type { Ledger, PaginatedLedgers } from '../types/api';
import ConfirmDialog from '../components/ConfirmDialog';
import EmptyState from '../components/EmptyState';

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

export default function LedgersPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingLedgerId, setDeletingLedgerId] = useState<number | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [pendingDeleteLedgerId, setPendingDeleteLedgerId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 20;

  useEffect(() => {
    const state = location.state as { success?: string } | null;
    if (state?.success) {
      setSuccess(state.success);
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  async function loadLedgers(currentPage: number, currentSearch: string) {
    try {
      setLoading(true);
      setError('');
      const res = await api.get<PaginatedLedgers>('/ledgers/', {
        params: { page: currentPage, page_size: pageSize, search: currentSearch },
      });
      setLedgers(res.data.items);
      setTotal(res.data.total);
      setTotalPages(res.data.total_pages);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load ledgers'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadLedgers(page, search);
  }, [page, search]);

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
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to delete ledger'));
    } finally {
      setDeletingLedgerId(null);
      setPendingDeleteLedgerId(null);
    }
  }

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
            <div className="ledger-search">
              <label htmlFor="ledger-search" className="sr-only">
                Search ledgers by name
              </label>
              <Search size={16} className="ledger-search__icon" aria-hidden="true" />
              <input
                id="ledger-search"
                className="input ledger-search__input"
                type="search"
                placeholder="Search ledgers by name, GST or contact..."
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
              {search ? (
                <button
                  type="button"
                  className="ledger-search__clear"
                  onClick={() => {
                    setSearch('');
                    setPage(1);
                  }}
                  title="Clear search"
                  aria-label="Clear search"
                >
                  <X size={14} />
                </button>
              ) : null}
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
                <p className="sr-only" role="status">
                  Loading ledgers...
                </p>
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
                              <span className="ledger-chip">
                                <Phone size={13} />
                                {ledger.phone_number}
                              </span>
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

          {totalPages > 1 ? (
            <div className="ledger-pagination">
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
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
                onClick={() => setPage((p) => p + 1)}
                title="Next page"
                aria-label="Next page"
              >
                Next
                <ChevronRight size={15} />
              </button>
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
