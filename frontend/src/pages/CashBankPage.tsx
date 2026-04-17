import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type { CompanyAccount, CompanyProfile, Ledger, Payment } from '../types/api';
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
        date: payment.date,
        voucherLabel: payment.voucher_type === 'receipt' ? 'Receipt' : 'Payment',
        ledgerName: ledgerNameById.get(payment.ledger_id) || 'Unknown ledger',
        particulars: `${payment.voucher_type === 'receipt' ? 'Receipt' : 'Payment'}${payment.mode ? ` (${payment.mode})` : ''}`,
        debit: payment.voucher_type === 'payment' ? payment.amount : 0,
        credit: payment.voucher_type === 'receipt' ? payment.amount : 0,
      }));
  }, [payments, selectedAccountId, ledgerNameById, period.fromDate, period.toDate]);

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

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

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
                    </div>
                    <span className="invoice-row__price">
                      {entry.debit > 0
                        ? `Dr ${formatCurrency(entry.debit, activeCurrencyCode)}`
                        : `Cr ${formatCurrency(entry.credit, activeCurrencyCode)}`}
                    </span>
                  </div>
                ))
              : null}
          </div>
        </article>
      </section>
    </div>
  );
}
