import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type { CompanyAccount, CompanyProfile, Ledger, Payment, PaymentCreate, PaymentUpdate } from '../types/api';
import formatCurrency from '../utils/formatting';
import { useFY } from '../context/FYContext';

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
  const toIso = (date: Date) => date.toISOString().slice(0, 10);

  return {
    fromDate: toIso(firstDay),
    toDate: toIso(today),
  };
}

export default function CashBankPage() {
  const navigate = useNavigate();
  const { activeFY } = useFY();
  const [period, setPeriod] = useState(() => ({
    fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
    toDate: activeFY?.end_date ?? defaultDateRange().toDate,
  }));
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [accounts, setAccounts] = useState<CompanyAccount[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [showEntryModal, setShowEntryModal] = useState(false);
  const [entrySubmitting, setEntrySubmitting] = useState(false);
  const [editingEntry, setEditingEntry] = useState<null | {
    id: number;
    voucher_type: 'receipt' | 'payment';
    amount: number;
    date: string;
    notes: string;
  }>(null);

  const [entryForm, setEntryForm] = useState({
    entryType: 'debit' as 'debit' | 'credit',
    amount: 0,
    date: new Date().toISOString().slice(0, 10),
    description: '',
  });

  const activeCurrencyCode = company?.currency_code || 'USD';

  useEffect(() => {
    if (selectedAccountId !== '') return;
    if (accounts.length === 0) return;
    setSelectedAccountId(String(accounts[0].id));
  }, [accounts, selectedAccountId]);

  async function loadData() {
    try {
      setLoading(true);
      setError('');

      const [accountsResponse, paymentsResponse, ledgersResponse, companyResponse] = await Promise.all([
        api.get<CompanyAccount[]>('/company-accounts/'),
        api.get<Payment[]>('/payments/'),
        api.get<{ items: Ledger[] }>('/ledgers/', { params: { page_size: 500 } }),
        api.get<CompanyProfile>('/company/'),
      ]);

      setAccounts(accountsResponse.data);
      setPayments(paymentsResponse.data);
      setLedgers(ledgersResponse.data.items);
      setCompany(companyResponse.data);
    } catch (err) {
      setPayments([]);
      setError(getApiErrorMessage(err, 'Unable to load cash & bank register'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [period.fromDate, period.toDate]);

  useEffect(() => {
    setPeriod({
      fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
      toDate: activeFY?.end_date ?? defaultDateRange().toDate,
    });
  }, [activeFY]);

  const selectedAccount = useMemo(() => (
    selectedAccountId ? accounts.find((account) => account.id === Number(selectedAccountId)) ?? null : null
  ), [accounts, selectedAccountId]);

  const ledgerNameById = useMemo(() => {
    return new Map(ledgers.map((ledger) => [ledger.id, ledger.name]));
  }, [ledgers]);

  const accountEntries = useMemo(() => {
    const fromMs = new Date(`${period.fromDate}T00:00:00`).getTime();
    const toMs = new Date(`${period.toDate}T23:59:59`).getTime();

    return payments
      .filter((payment) => payment.voucher_type === 'receipt' || payment.voucher_type === 'payment')
      .filter((payment) => {
        const paymentMs = new Date(payment.date).getTime();
        return paymentMs >= fromMs && paymentMs <= toMs;
      })
      .filter((payment) => {
        if (selectedAccountId === '') {
          return payment.account_id == null;
        }

        return payment.account_id === Number(selectedAccountId);
      })
      .map((payment) => ({
        id: payment.id,
        voucherType: payment.voucher_type,
        date: payment.date,
        voucherLabel: payment.voucher_type === 'receipt' ? 'Receipt' : 'Payment',
        ledgerName: payment.ledger_id != null ? (ledgerNameById.get(payment.ledger_id) || 'Unknown ledger') : 'Account entry',
        particulars: `${payment.voucher_type === 'receipt' ? 'Receipt' : 'Payment'}${payment.mode ? ` (${payment.mode})` : ''}`,
        description: payment.notes || '',
        debit: payment.voucher_type === 'payment' ? payment.amount : 0,
        credit: payment.voucher_type === 'receipt' ? payment.amount : 0,
      }));
  }, [payments, selectedAccountId, ledgerNameById, period.fromDate, period.toDate]);

  function resetEntryForm() {
    setEntryForm({
      entryType: 'debit',
      amount: 0,
      date: new Date().toISOString().slice(0, 10),
      description: '',
    });
  }

  function openCreateEntryModal() {
    resetEntryForm();
    setEditingEntry(null);
    setShowEntryModal(true);
  }

  function openEditEntryModal(entryId: number) {
    const payment = payments.find((item) => item.id === entryId);
    if (!payment) {
      setError('Entry not found');
      return;
    }

    setEditingEntry({
      id: payment.id,
      voucher_type: payment.voucher_type === 'payment' ? 'payment' : 'receipt',
      amount: Number(payment.amount),
      date: payment.date,
      notes: payment.notes || '',
    });

    setEntryForm({
      entryType: payment.voucher_type === 'payment' ? 'debit' : 'credit',
      amount: Number(payment.amount),
      date: payment.date.slice(0, 10),
      description: payment.notes || '',
    });
    setShowEntryModal(true);
  }

  async function handleSubmitEntry(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAccount) {
      setError('Select an account to add entry');
      return;
    }
    if (entryForm.amount <= 0) {
      setError('Amount must be greater than 0');
      return;
    }

    const voucherType = entryForm.entryType === 'debit' ? 'payment' : 'receipt';
    const isoDate = `${entryForm.date}T00:00:00`;

    try {
      setEntrySubmitting(true);
      setError('');

      if (editingEntry) {
        const payload: PaymentUpdate = {
          voucher_type: voucherType,
          amount: entryForm.amount,
          account_id: selectedAccount.id,
          date: isoDate,
          mode: selectedAccount.account_type,
          notes: entryForm.description.trim() || undefined,
        };
        await api.put<Payment>(`/payments/${editingEntry.id}`, payload);
        setSuccess('Entry updated');
      } else {
        const payload: PaymentCreate = {
          ledger_id: null,
          voucher_type: voucherType,
          amount: entryForm.amount,
          account_id: selectedAccount.id,
          date: isoDate,
          mode: selectedAccount.account_type,
          notes: entryForm.description.trim() || undefined,
        };
        await api.post<Payment>('/payments/', payload);
        setSuccess('Entry added');
      }

      setShowEntryModal(false);
      setEditingEntry(null);
      resetEntryForm();
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to save entry'));
    } finally {
      setEntrySubmitting(false);
    }
  }

  async function handleDeleteEntry(entryId: number) {
    const confirmed = window.confirm('Delete this entry?');
    if (!confirmed) return;

    try {
      setError('');
      await api.delete(`/payments/${entryId}`);
      setSuccess('Entry deleted');
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to delete entry'));
    }
  }

  const totals = useMemo(() => {
    const totalDebit = accountEntries.reduce((sum, entry) => sum + entry.debit, 0);
    const totalCredit = accountEntries.reduce((sum, entry) => sum + entry.credit, 0);
    const openingBalance = selectedAccount ? Number(selectedAccount.opening_balance || 0) : 0;
    const availableBalance = openingBalance + totalCredit - totalDebit;

    return {
      totalDebit,
      totalCredit,
      openingBalance,
      availableBalance,
    };
  }, [accountEntries, selectedAccount]);

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Accounting</p>
          <h1 className="page-title">Cash &amp; Bank</h1>
          <p className="section-copy">Track account-wise receipts, payments, and available balance in one register.</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div className="status-chip">{accountEntries.length} entries</div>
          <button
            type="button"
            className="button button--primary"
            onClick={() => navigate('/cash-bank/accounts')}
            title="Add or manage cash and bank accounts"
            aria-label="Manage Accounts"
          >
            Manage Account
          </button>
        </div>
      </section>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Filters</p>
              <h2 className="nav-panel__title">Account and period</h2>
            </div>
          </div>

          <div className="field-grid">
            <div className="field">
              <label htmlFor="cash-bank-account">Account</label>
              <select
                id="cash-bank-account"
                className="select"
                value={selectedAccountId}
                onChange={(event) => setSelectedAccountId(event.target.value)}
              >
                <option value="">Unallocated</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.display_name} ({account.account_type})
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="cash-bank-from">From</label>
              <input
                id="cash-bank-from"
                className="input"
                type="date"
                value={period.fromDate}
                onChange={(event) => setPeriod((current) => ({ ...current, fromDate: event.target.value }))}
              />
            </div>

            <div className="field">
              <label htmlFor="cash-bank-to">To</label>
              <input
                id="cash-bank-to"
                className="input"
                type="date"
                value={period.toDate}
                onChange={(event) => setPeriod((current) => ({ ...current, toDate: event.target.value }))}
              />
            </div>
          </div>

          <div className="summary-box">
            <p className="eyebrow">Account totals</p>
            <p className="summary-box__value">{formatCurrency(totals.availableBalance, activeCurrencyCode)}</p>
            <p className="muted-text">Opening available balance {formatCurrency(totals.openingBalance, activeCurrencyCode)}</p>
            <p className="muted-text">Dr {formatCurrency(totals.totalDebit, activeCurrencyCode)} · Cr {formatCurrency(totals.totalCredit, activeCurrencyCode)}</p>
          </div>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Register</p>
              <h2 className="nav-panel__title">
                {selectedAccount ? `${selectedAccount.display_name} entries` : 'Unallocated entries'}
              </h2>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              {selectedAccount ? (
                <button
                  type="button"
                  className="button button--primary"
                  onClick={openCreateEntryModal}
                  title="Add debit or credit entry"
                  aria-label="Add debit or credit entry"
                >
                  Add Entry
                </button>
              ) : null}
            </div>
          </div>

          <div className="invoice-list">
            {loading ? <div className="empty-state">Loading account register...</div> : null}
            {!loading && accountEntries.length === 0 ? (
              <div className="empty-state">No entries found for selected filters.</div>
            ) : null}
            {!loading
              ? accountEntries.map((entry, idx) => (
                  <div key={`${entry.id}-${idx}`} className="invoice-row">
                    <div className="invoice-row__meta">
                      <strong>{entry.voucherLabel} #{entry.id}</strong>
                      <span className="table-subtext">
                        {new Date(entry.date).toLocaleDateString()} · {entry.ledgerName}
                      </span>
                      <span className="table-subtext">{entry.particulars}</span>
                      {entry.description ? <span className="table-subtext">{entry.description}</span> : null}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span className="invoice-row__price">
                        {entry.debit > 0
                          ? `Dr ${formatCurrency(entry.debit, activeCurrencyCode)}`
                          : `Cr ${formatCurrency(entry.credit, activeCurrencyCode)}`}
                      </span>
                      <button
                        type="button"
                        className="button button--ghost button--small"
                        onClick={() => openEditEntryModal(entry.id)}
                        title="Edit entry"
                        aria-label="Edit entry"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="button button--ghost button--small"
                        onClick={() => void handleDeleteEntry(entry.id)}
                        title="Delete entry"
                        aria-label="Delete entry"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))
              : null}
          </div>
        </article>
      </section>

      {showEntryModal ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" onClick={() => setShowEntryModal(false)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="panel stack">
              <div className="panel__header">
                <h2 className="nav-panel__title">{editingEntry ? 'Edit entry' : 'Add debit / credit entry'}</h2>
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => setShowEntryModal(false)}
                  title="Close entry dialog"
                  aria-label="Close entry dialog"
                >
                  ✕
                </button>
              </div>

              <form onSubmit={(event) => void handleSubmitEntry(event)} className="stack">
                <div className="field">
                  <label htmlFor="entry-type">Type</label>
                  <select
                    id="entry-type"
                    className="input"
                    value={entryForm.entryType}
                    onChange={(event) => setEntryForm((current) => ({
                      ...current,
                      entryType: event.target.value as 'debit' | 'credit',
                    }))}
                  >
                    <option value="debit">Debit (withdrawal / outflow)</option>
                    <option value="credit">Credit (deposit / inflow)</option>
                  </select>
                </div>

                <div className="field">
                  <label htmlFor="entry-amount">Amount</label>
                  <input
                    id="entry-amount"
                    className="input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={entryForm.amount || ''}
                    onChange={(event) => setEntryForm((current) => ({
                      ...current,
                      amount: parseFloat(event.target.value) || 0,
                    }))}
                    required
                  />
                </div>

                <div className="field">
                  <label htmlFor="entry-date">Date</label>
                  <input
                    id="entry-date"
                    className="input"
                    type="date"
                    value={entryForm.date}
                    onChange={(event) => setEntryForm((current) => ({
                      ...current,
                      date: event.target.value,
                    }))}
                    required
                  />
                </div>

                <div className="field">
                  <label htmlFor="entry-description">Description</label>
                  <input
                    id="entry-description"
                    className="input"
                    type="text"
                    placeholder="e.g. ATM withdrawal, branch cash deposit"
                    value={entryForm.description}
                    onChange={(event) => setEntryForm((current) => ({
                      ...current,
                      description: event.target.value,
                    }))}
                  />
                </div>

                <button
                  type="submit"
                  className="button button--primary"
                  disabled={entrySubmitting}
                  title="Save entry"
                  aria-label="Save entry"
                >
                  {entrySubmitting ? 'Saving...' : 'Save entry'}
                </button>
              </form>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
