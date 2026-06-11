import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyAccount, OutstandingInvoice, Payment, PaymentCreate, PaymentInvoiceAllocation } from '../types/api';
import { fetchOutstandingInvoices } from '../features/invoices/api';
import formatCurrency from '../utils/formatting';
import { formatInvoiceDateLabel } from '../utils/invoiceDueDate';
import EmptyState from './EmptyState';
import { useFY } from '../context/FYContext';

interface ReceiptModalProps {
  ledgerId: number;
  ledgerName: string;
  currencyCode?: string;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

function sumAllocatedAmount(allocations: PaymentInvoiceAllocation[] | undefined): number {
  return (allocations ?? []).reduce((total, allocation) => total + Number(allocation.allocated_amount || 0), 0);
}

function buildSuggestedAllocations(invoices: OutstandingInvoice[]): PaymentInvoiceAllocation[] {
  return invoices
    .filter((invoice) => (invoice.suggested_allocation_amount || 0) > 0)
    .map((invoice) => ({
      invoice_id: invoice.id,
      invoice_number: invoice.invoice_number,
      invoice_date: invoice.invoice_date,
      due_date: invoice.due_date,
      allocated_amount: invoice.suggested_allocation_amount || 0,
    }));
}

function upsertAllocation(
  allocations: PaymentInvoiceAllocation[] | undefined,
  invoice: OutstandingInvoice,
  allocatedAmount: number,
): PaymentInvoiceAllocation[] {
  const nextAllocations = [...(allocations ?? [])];
  const existingIndex = nextAllocations.findIndex((allocation) => allocation.invoice_id === invoice.id);
  const nextAllocation: PaymentInvoiceAllocation = {
    invoice_id: invoice.id,
    invoice_number: invoice.invoice_number,
    invoice_date: invoice.invoice_date,
    due_date: invoice.due_date,
    allocated_amount: allocatedAmount,
  };

  if (existingIndex >= 0) {
    nextAllocations[existingIndex] = { ...nextAllocations[existingIndex], ...nextAllocation };
    return nextAllocations;
  }

  return [...nextAllocations, nextAllocation];
}

function removeAllocation(allocations: PaymentInvoiceAllocation[] | undefined, invoiceId: number): PaymentInvoiceAllocation[] {
  return (allocations ?? []).filter((allocation) => allocation.invoice_id !== invoiceId);
}

export default function ReceiptModal({
  ledgerId,
  ledgerName,
  currencyCode = 'INR',
  onClose,
  onSuccess,
  onError,
}: ReceiptModalProps) {
  const { activeFY } = useFY();

  const [form, setForm] = useState<PaymentCreate>({
    ledger_id: ledgerId,
    voucher_type: 'receipt',
    amount: 0,
    account_id: null,
    date: new Date().toISOString().slice(0, 16),
    mode: '',
    reference: '',
    notes: '',
    invoice_allocations: [],
  });
  const [companyAccounts, setCompanyAccounts] = useState<CompanyAccount[]>([]);
  const [outstandingInvoices, setOutstandingInvoices] = useState<OutstandingInvoice[]>([]);
  const [loadingOutstanding, setLoadingOutstanding] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  // Load company accounts
  useEffect(() => {
    let cancelled = false;
    api.get<CompanyAccount[]>('/company-accounts/')
      .then((res) => { if (!cancelled) setCompanyAccounts(res.data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Load outstanding invoices when amount or voucher type changes
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoadingOutstanding(true);
        const invoices = await fetchOutstandingInvoices({
          ledgerId,
          voucherType: 'receipt',
          amount: form.amount > 0 ? form.amount : undefined,
        });
        if (!cancelled) {
          setOutstandingInvoices(invoices);
        }
      } catch (err) {
        if (!cancelled) {
          onError(getApiErrorMessage(err, 'Unable to load outstanding invoices'));
        }
      } finally {
        if (!cancelled) {
          setLoadingOutstanding(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [ledgerId, form.amount]);

  // Reset search when closing
  useEffect(() => {
    return () => setSearchQuery('');
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (form.amount <= 0) {
      onError('Amount must be greater than 0');
      return;
    }
    try {
      setSubmitting(true);
      const res = await api.post<Payment>('/payments/', form);
      const warningMsg = res.data.warnings?.includes('invoice_date_outside_fy') && activeFY
        ? ` ⚠️ This date is outside the active financial year (${activeFY.label}). The receipt was still recorded.`
        : '';
      onSuccess(`Receipt recorded against ${ledgerName}` + warningMsg);
      onClose();
    } catch (err) {
      onError(getApiErrorMessage(err, 'Unable to record receipt'));
    } finally {
      setSubmitting(false);
    }
  }

  const allocatedTotal = sumAllocatedAmount(form.invoice_allocations);
  const remainingUnallocated = form.amount - allocatedTotal;
  const filteredInvoices = searchQuery.trim()
    ? outstandingInvoices.filter((inv) =>
        (inv.invoice_number ?? '').toLowerCase().includes(searchQuery.trim().toLowerCase())
      )
    : outstandingInvoices;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Receipt</p>
              <h2 className="nav-panel__title">Record Receipt — {ledgerName}</h2>
            </div>
            <button type="button" className="button button--ghost" onClick={onClose} title="Close" aria-label="Close">✕</button>
          </div>
          <form onSubmit={(e) => void handleSubmit(e)} className="stack">
            <div className="field">
              <label htmlFor="rcpt-amount">Amount</label>
              <input
                id="rcpt-amount"
                className="input"
                type="number"
                min="0.01"
                step="0.01"
                value={form.amount || ''}
                onChange={(e) => setForm((f) => ({ ...f, amount: parseFloat(e.target.value) || 0 }))}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="rcpt-account">Account</label>
              <select
                id="rcpt-account"
                className="input"
                value={form.account_id ?? ''}
                onChange={(e) => setForm((f) => ({ ...f, account_id: e.target.value ? Number(e.target.value) : null }))}
              >
                <option value="">Unallocated</option>
                {companyAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.display_name} ({account.account_type})
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="rcpt-date">Date</label>
              <input
                id="rcpt-date"
                className="input"
                type="datetime-local"
                value={form.date}
                onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
              />
              {activeFY !== null && form.date && (
                form.date.slice(0, 10) < activeFY.start_date ||
                form.date.slice(0, 10) > activeFY.end_date
              ) ? (
                <p className="field-warning">
                  ⚠️ This date is outside the active financial year ({activeFY.label}). The receipt will still be recorded.
                </p>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="rcpt-mode">Mode</label>
              <select
                id="rcpt-mode"
                className="input"
                value={form.mode}
                onChange={(e) => setForm((f) => ({ ...f, mode: e.target.value }))}
              >
                <option value="">Select mode</option>
                <option value="cash">Cash</option>
                <option value="bank">Bank Transfer</option>
                <option value="upi">UPI</option>
                <option value="cheque">Cheque</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="rcpt-ref">Reference (optional)</label>
              <input
                id="rcpt-ref"
                className="input"
                type="text"
                placeholder="Cheque no, txn ID..."
                value={form.reference}
                onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="rcpt-notes">Notes (optional)</label>
              <input
                id="rcpt-notes"
                className="input"
                type="text"
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              />
            </div>

            {/* Invoice Allocation Section */}
            <div className="summary-box stack" style={{ gap: '12px' }}>
              <div className="panel__header" style={{ marginBottom: 0 }}>
                <div>
                  <p className="eyebrow">Invoice Allocation</p>
                  <h3 className="nav-panel__title" style={{ margin: 0 }}>Allocate against invoices</h3>
                </div>
                <button
                  type="button"
                  className="button button--secondary button--small"
                  onClick={() => setForm((f) => ({ ...f, invoice_allocations: buildSuggestedAllocations(outstandingInvoices) }))}
                  disabled={loadingOutstanding || outstandingInvoices.length === 0 || form.amount <= 0}
                >
                  Auto Select Oldest
                </button>
              </div>

              <p className="muted-text" style={{ margin: 0 }}>
                Allocated {formatCurrency(allocatedTotal, currencyCode)}
                {' · '}
                {remainingUnallocated >= 0
                  ? `Unallocated ${formatCurrency(remainingUnallocated, currencyCode)}`
                  : `Over-allocated by ${formatCurrency(Math.abs(remainingUnallocated), currencyCode)}`}
              </p>

              {!loadingOutstanding && outstandingInvoices.length > 0 ? (
                <input
                  type="search"
                  className="input"
                  placeholder="Search by invoice number…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  aria-label="Search invoices by number"
                />
              ) : null}

              {loadingOutstanding ? <EmptyState message="Loading invoice options..." /> : null}
              {!loadingOutstanding && outstandingInvoices.length === 0 ? (
                <EmptyState message="No outstanding invoices are available for this ledger." />
              ) : null}
              {!loadingOutstanding && outstandingInvoices.length > 0 && filteredInvoices.length === 0 ? (
                <p className="muted-text" style={{ margin: 0 }}>No invoices match your search.</p>
              ) : null}

              {!loadingOutstanding && filteredInvoices.length > 0 ? (
                <div className="stack" style={{ gap: '10px', maxHeight: '320px', overflowY: 'auto', paddingRight: '4px' }}>
                  {filteredInvoices.map((invoice) => {
                    const existingAllocation = (form.invoice_allocations ?? []).find(
                      (allocation) => allocation.invoice_id === invoice.id
                    );
                    const isSelected = Boolean(existingAllocation);

                    return (
                      <div key={invoice.id} className="summary-box" style={{ padding: '14px' }}>
                        <div style={{ display: 'grid', gap: '10px' }}>
                          <label style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', cursor: 'pointer' }}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={(event) => {
                                if (!event.target.checked) {
                                  setForm((f) => ({ ...f, invoice_allocations: removeAllocation(f.invoice_allocations, invoice.id) }));
                                  return;
                                }
                                const defaultAmount = invoice.suggested_allocation_amount || invoice.remaining_amount;
                                setForm((f) => ({ ...f, invoice_allocations: upsertAllocation(f.invoice_allocations, invoice, defaultAmount) }));
                              }}
                            />
                            <div style={{ display: 'grid', gap: '4px', flex: 1 }}>
                              <strong>{invoice.invoice_number || `#${invoice.id}`}</strong>
                              <span className="table-subtext">
                                Invoice {formatInvoiceDateLabel(invoice.invoice_date)}
                                {' · '}
                                Due {formatInvoiceDateLabel(invoice.due_date)}
                                {' · '}
                                Remaining {formatCurrency(invoice.remaining_amount, currencyCode)}
                              </span>
                              <span className="table-subtext">
                                Status {invoice.payment_status}
                                {typeof invoice.due_in_days === 'number' ? ` · ${invoice.due_in_days} days` : ''}
                              </span>
                            </div>
                          </label>

                          {isSelected ? (
                            <div className="field" style={{ marginLeft: '28px' }}>
                              <label htmlFor={`rcpt-allocation-${invoice.id}`}>Allocated amount</label>
                              <input
                                id={`rcpt-allocation-${invoice.id}`}
                                className="input"
                                type="number"
                                min="0.01"
                                step="0.01"
                                value={existingAllocation?.allocated_amount || ''}
                                onChange={(event) => {
                                  const nextAmount = parseFloat(event.target.value) || 0;
                                  setForm((f) => ({ ...f, invoice_allocations: upsertAllocation(f.invoice_allocations, invoice, nextAmount) }));
                                }}
                              />
                            </div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>

            <button type="submit" className="button button--primary" disabled={submitting} title="Save receipt" aria-label="Save receipt">
              {submitting ? 'Saving...' : 'Save Receipt'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
