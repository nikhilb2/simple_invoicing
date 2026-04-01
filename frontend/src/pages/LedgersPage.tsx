import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import type { Ledger, PaginatedLedgers } from '../types/api';
import ConfirmDialog from '../components/ConfirmDialog';

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

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Ledgers</p>
          <h1 className="page-title">Ledger master</h1>
          <p className="section-copy">A minimal Tally-style ledger registry with period-wise view of sales and purchase postings.</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div className="status-chip">{total} ledgers listed</div>
          <button className="button button--primary" onClick={() => navigate('/ledgers/new')}>
            Create ledger
          </button>
        </div>
      </section>

      {error ? <div className="status-banner status-banner--error">{error}</div> : null}
      {success ? <div className="status-banner status-banner--success">{success}</div> : null}

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Registry</p>
              <h2 className="nav-panel__title">All ledgers</h2>
            </div>
          </div>

          <div className="field">
            <label htmlFor="ledger-search">Search by name</label>
            <input
              id="ledger-search"
              className="input"
              type="search"
              placeholder="Type to search ledgers..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>

          <div className="table-list">
            {loading ? <div className="empty-state">Loading ledgers...</div> : null}
            {!loading && ledgers.length === 0 ? <div className="empty-state">No ledgers have been created yet.</div> : null}
            {!loading
              ? ledgers.map((ledger) => (
                  <div key={ledger.id} className="table-row">
                    <div className="table-row__meta">
                      <strong>{ledger.name}</strong>
                      <span className="table-subtext">
                        {ledger.gst} · {ledger.phone_number}
                      </span>
                      {(ledger.email || ledger.website) ? (
                        <span className="table-subtext">
                          {ledger.email ? `Email: ${ledger.email}` : ''}
                          {ledger.email && ledger.website ? ' · ' : ''}
                          {ledger.website ? `Web: ${ledger.website}` : ''}
                        </span>
                      ) : null}
                      {(ledger.bank_name || ledger.account_number) ? (
                        <span className="table-subtext">
                          Bank: {ledger.bank_name || 'N/A'}
                          {ledger.branch_name ? ` (${ledger.branch_name})` : ''} · A/C: {ledger.account_number || 'N/A'}
                          {ledger.ifsc_code ? ` · IFSC: ${ledger.ifsc_code}` : ''}
                        </span>
                      ) : null}
                      <span className="table-subtext">{ledger.address}</span>
                    </div>
                    <span className="table-subtext text-right">Ledger #{ledger.id}</span>
                    <div className="table-row__actions">
                      <button type="button" className="button button--ghost" onClick={() => navigate(`/ledgers/${ledger.id}`)}>
                        View
                      </button>
                      <button type="button" className="button button--ghost" onClick={() => navigate(`/ledgers/${ledger.id}/edit`)}>
                        Edit
                      </button>
                      <button
                        type="button"
                        className="button button--danger"
                        onClick={() => handleDeleteLedger(ledger.id)}
                        disabled={deletingLedgerId === ledger.id}
                      >
                        {deletingLedgerId === ledger.id ? 'Deleting...' : 'Delete'}
                      </button>
                    </div>
                  </div>
                ))
              : null}
          </div>

          {totalPages > 1 ? (
            <div className="button-row" style={{ justifyContent: 'center', paddingTop: '8px' }}>
              <button
                type="button"
                className="button button--ghost"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </button>
              <span className="muted-text" style={{ alignSelf: 'center' }}>
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className="button button--ghost"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
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