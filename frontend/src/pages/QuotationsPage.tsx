import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Ban, Check, Copy, FileText, Pencil, Plus, RotateCcw, X } from 'lucide-react';
import { getApiErrorMessage } from '../api/client';
import ConfirmDialog from '../components/ConfirmDialog';
import EmptyState from '../components/EmptyState';
import LoadingState from '../components/LoadingState';
import ModalCloseButton from '../components/ModalCloseButton';
import type { PreviewAction } from '../components/PreviewToolbar';
import QuotationPreview from '../components/QuotationPreview';
import QuotationsTable from '../components/QuotationsTable';
import SearchInput from '../components/SearchInput';
import StatusToasts from '../components/StatusToasts';
import {
  cancelQuotation,
  duplicateQuotation,
  fetchQuotations,
  setQuotationStatus,
} from '../features/quotations/api';
import { quotationQueryKeys } from '../features/quotations/queryKeys';
import type {
  Quotation,
  QuotationDisplayStatus,
  QuotationDocumentType,
  QuotationSettableStatus,
} from '../types/api';
import formatCurrency, { formatDate } from '../utils/formatting';
import {
  QUOTATION_DOCUMENT_LABELS,
  QUOTATION_STATUS_FILTERS,
  QUOTATION_STATUS_LABELS,
  allowedQuotationActions,
} from '../utils/quotationStatus';

const PAGE_SIZE = 20;

function readStatus(value: string | null): QuotationDisplayStatus | undefined {
  return QUOTATION_STATUS_FILTERS.some((chip) => chip.value === value) ? (value as QuotationDisplayStatus) : undefined;
}

function readDocumentType(value: string | null): QuotationDocumentType | undefined {
  return value === 'quotation' || value === 'proforma' ? value : undefined;
}

type StatusAction = { quotation: Quotation; status: QuotationSettableStatus };

const STATUS_ACTION_TITLES: Record<QuotationSettableStatus, string> = {
  accepted: 'Mark accepted',
  declined: 'Mark declined',
  open: 'Reopen',
};

export default function QuotationsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const status = readStatus(searchParams.get('status'));
  const documentType = readDocumentType(searchParams.get('type'));
  const search = searchParams.get('search') ?? '';
  const page = Math.max(1, Number(searchParams.get('page')) || 1);

  const [previewing, setPreviewing] = useState<Quotation | null>(null);
  const [statusAction, setStatusAction] = useState<StatusAction | null>(null);
  const [statusNote, setStatusNote] = useState('');
  const [cancelling, setCancelling] = useState<Quotation | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const filters = useMemo(
    () => ({ page, pageSize: PAGE_SIZE, search, status, documentType }),
    [page, search, status, documentType],
  );
  const listQuery = useQuery({
    queryKey: quotationQueryKeys.list(filters),
    queryFn: () => fetchQuotations(filters),
    // Cancelling or restoring an invoice, on another page, changes these statuses.
    refetchOnMount: 'always',
  });
  const counts = listQuery.data?.status_counts ?? {};

  function setFilter(key: string, value: string | undefined) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== 'page') next.delete('page');
      return next;
    }, { replace: true });
  }

  function closeStatusDialog() {
    setStatusAction(null);
    setStatusNote('');
  }

  /** After any change: refresh the list, and keep an open preview showing the truth. */
  function applied(updated: Quotation, message: string) {
    setError('');
    setSuccess(message);
    setPreviewing((current) => (current && current.id === updated.id ? updated : current));
    return queryClient.invalidateQueries({ queryKey: quotationQueryKeys.all });
  }

  const statusMutation = useMutation({
    mutationFn: ({ quotation, status: target, note }: StatusAction & { note: string }) =>
      setQuotationStatus(quotation.id, target, note),
    onSuccess: async (updated, { status: target }) => {
      closeStatusDialog();
      await applied(updated, `${updated.quotation_number} is now ${QUOTATION_STATUS_LABELS[target].toLowerCase()}.`);
    },
    onError: (err) => {
      closeStatusDialog();
      setError(getApiErrorMessage(err, 'Unable to change the status'));
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (quotation: Quotation) => cancelQuotation(quotation.id),
    onSuccess: async (updated) => {
      setCancelling(null);
      await applied(updated, `${updated.quotation_number} cancelled. It keeps its number.`);
    },
    onError: (err) => {
      setCancelling(null);
      setError(getApiErrorMessage(err, 'Unable to cancel'));
    },
  });

  const duplicateMutation = useMutation({
    mutationFn: (quotation: Quotation) => duplicateQuotation(quotation.id),
    onSuccess: async (created) => {
      setPreviewing(null);
      await applied(created, `Created ${created.quotation_number}. Review it before sending.`);
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to duplicate')),
  });

  function convert(quotation: Quotation) {
    navigate(`/invoices?from_quotation=${quotation.id}`);
  }

  function menuActionsFor(quotation: Quotation): PreviewAction[] {
    const allowed = allowedQuotationActions(quotation);
    const actions: PreviewAction[] = [];
    const add = (condition: boolean, action: PreviewAction) => {
      if (condition) actions.push(action);
    };
    add(allowed.includes('convert'), {
      label: 'Convert to invoice',
      icon: <FileText size={16} aria-hidden="true" />,
      onClick: () => convert(quotation),
    });
    add(allowed.includes('edit'), {
      label: 'Edit',
      icon: <Pencil size={16} aria-hidden="true" />,
      onClick: () => navigate(`/invoices?edit_quotation=${quotation.id}`),
    });
    add(allowed.includes('accept'), {
      label: STATUS_ACTION_TITLES.accepted,
      icon: <Check size={16} aria-hidden="true" />,
      onClick: () => setStatusAction({ quotation, status: 'accepted' }),
    });
    add(allowed.includes('decline'), {
      label: STATUS_ACTION_TITLES.declined,
      icon: <X size={16} aria-hidden="true" />,
      onClick: () => setStatusAction({ quotation, status: 'declined' }),
    });
    add(allowed.includes('reopen'), {
      label: STATUS_ACTION_TITLES.open,
      icon: <RotateCcw size={16} aria-hidden="true" />,
      onClick: () => setStatusAction({ quotation, status: 'open' }),
    });
    add(allowed.includes('duplicate'), {
      label: 'Duplicate',
      icon: <Copy size={16} aria-hidden="true" />,
      onClick: () => duplicateMutation.mutate(quotation),
    });
    add(allowed.includes('cancel'), {
      label: 'Cancel document',
      icon: <Ban size={16} aria-hidden="true" />,
      onClick: () => setCancelling(quotation),
    });
    return actions;
  }

  const rows = listQuery.data?.items ?? [];
  const noFilters = !status && !documentType && !search;

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Sales</p>
          <h1 className="page-title">Quotations</h1>
          <p className="section-copy">
            Quotations and proforma invoices. Offers only: nothing here affects stock, ledgers, reports or returns until you convert it to an invoice.
          </p>
        </div>
        <div className="button-row">
          <Link className="button button--primary" to="/invoices?new=quotation">
            <Plus size={14} /> New quotation
          </Link>
          <Link className="button button--secondary" to="/invoices?new=proforma">
            <Plus size={14} /> New proforma
          </Link>
        </div>
      </section>

      <StatusToasts
        error={error || (listQuery.error ? getApiErrorMessage(listQuery.error, 'Unable to load quotations') : '')}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="button-row" style={{ flexWrap: 'wrap' }} role="group" aria-label="Filter by status">
            <button
              type="button"
              className={`button ${!status ? 'button--secondary' : 'button--ghost'}`}
              aria-pressed={!status}
              onClick={() => setFilter('status', undefined)}
            >
              All
            </button>
            {QUOTATION_STATUS_FILTERS.map((chip) => (
              <button
                key={chip.value}
                type="button"
                className={`button ${status === chip.value ? 'button--secondary' : 'button--ghost'}`}
                aria-pressed={status === chip.value}
                data-testid={`quotation-filter-${chip.value}`}
                onClick={() => setFilter('status', chip.value)}
              >
                {chip.label}{counts[chip.value] ? ` (${counts[chip.value]})` : ''}
              </button>
            ))}
          </div>

          <div className="field-grid">
            <div className="field">
              <SearchInput
                id="quotation-search"
                label="Search quotations"
                wrapperClassName="ledger-search"
                inputClassName="input ledger-search__input"
                iconClassName="ledger-search__icon"
                clearClassName="ledger-search__clear"
                value={search}
                onChange={(value) => setFilter('search', value || undefined)}
                placeholder="Number or party"
              />
            </div>
            <div className="field">
              <label htmlFor="quotation-type" className="sr-only">Document type</label>
              <select
                id="quotation-type"
                className="select"
                value={documentType ?? ''}
                onChange={(event) => setFilter('type', event.target.value || undefined)}
              >
                <option value="">Quotations and proformas</option>
                <option value="quotation">{QUOTATION_DOCUMENT_LABELS.quotation}</option>
                <option value="proforma">{QUOTATION_DOCUMENT_LABELS.proforma}</option>
              </select>
            </div>
          </div>

          {listQuery.isLoading ? <LoadingState message="Loading quotations…" /> : null}

          {!listQuery.isLoading && rows.length === 0 ? (
            <EmptyState
              message={noFilters
                ? 'No quotations yet. A quotation or proforma invoice is an offer: it moves no stock and reaches no report until you convert it to an invoice.'
                : 'Nothing matches these filters. Try a different status or search.'}
            />
          ) : null}

          {rows.length > 0 ? (
            <QuotationsTable quotations={rows} onOpen={setPreviewing} onConvert={convert} />
          ) : null}

          {listQuery.data && listQuery.data.total_pages > 1 ? (
            <div className="button-row" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="button button--ghost" disabled={page <= 1} onClick={() => setFilter('page', String(page - 1))}>
                Previous
              </button>
              <span className="muted-text">Page {page} of {listQuery.data.total_pages}</span>
              <button type="button" className="button button--ghost" disabled={page >= listQuery.data.total_pages} onClick={() => setFilter('page', String(page + 1))}>
                Next
              </button>
            </div>
          ) : null}
        </article>
      </section>

      {previewing ? (
        <QuotationPreview
          quotation={previewing}
          menuActions={menuActionsFor(previewing)}
          meta={
            <>
              {formatCurrency(previewing.total_amount, previewing.company_currency_code || 'INR')}
              {' · '}
              {QUOTATION_STATUS_LABELS[previewing.display_status]}
              {previewing.valid_until ? ` · Valid until ${formatDate(previewing.valid_until)}` : ''}
            </>
          }
          onClose={() => setPreviewing(null)}
          onError={setError}
        />
      ) : null}

      {statusAction ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="quotation-status-title">
          <div className="modal-panel stack">
            <div className="panel__header">
              <h2 id="quotation-status-title" className="nav-panel__title">
                {STATUS_ACTION_TITLES[statusAction.status]}: {statusAction.quotation.quotation_number}
              </h2>
              <ModalCloseButton onClick={closeStatusDialog} label="Close" />
            </div>
            <div className="field">
              <label htmlFor="quotation-status-note">Note (optional)</label>
              <input
                id="quotation-status-note"
                className="input"
                type="text"
                value={statusNote}
                onChange={(event) => setStatusNote(event.target.value)}
                placeholder={statusAction.status === 'declined' ? 'Why they said no' : 'For example: PO 123 by email'}
              />
            </div>
            <div className="button-row" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="button button--ghost" onClick={closeStatusDialog}>
                Back
              </button>
              <button
                type="button"
                className="button button--primary"
                disabled={statusMutation.isPending}
                onClick={() => statusMutation.mutate({ ...statusAction, note: statusNote })}
              >
                {STATUS_ACTION_TITLES[statusAction.status]}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {cancelling ? (
        <ConfirmDialog
          title={`Cancel ${cancelling.quotation_number}?`}
          message="It stays on the list as cancelled and keeps its number. This cannot be undone. Duplicate it if you need it again."
          confirmText="Cancel document"
          cancelText="Keep it"
          danger
          confirmDisabled={cancelMutation.isPending}
          onConfirm={() => cancelMutation.mutate(cancelling)}
          onCancel={() => setCancelling(null)}
        />
      ) : null}
    </div>
  );
}
