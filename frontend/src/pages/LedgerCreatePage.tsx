import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type { Ledger, LedgerCreate } from '../types/api';

export default function LedgerCreatePage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const editingLedgerId = id ? Number(id) : null;

  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(!!editingLedgerId);
  const [error, setError] = useState('');
  const [form, setForm] = useState<LedgerCreate>({
    name: '',
    address: '',
    gst: '',
    opening_balance: null,
    phone_number: '',
    email: '',
    website: '',
    bank_name: '',
    branch_name: '',
    account_name: '',
    account_number: '',
    ifsc_code: '',
  });

  useEffect(() => {
    if (!editingLedgerId) return;
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const res = await api.get<Ledger>(`/ledgers/${editingLedgerId}`);
        if (cancelled) return;
        const l = res.data;
        setForm({
          name: l.name,
          address: l.address,
          gst: l.gst || '',
          opening_balance: l.opening_balance,
          phone_number: l.phone_number,
          email: l.email || '',
          website: l.website || '',
          bank_name: l.bank_name || '',
          branch_name: l.branch_name || '',
          account_name: l.account_name || '',
          account_number: l.account_number || '',
          ifsc_code: l.ifsc_code || '',
        });
      } catch (err) {
        if (!cancelled) setError(getApiErrorMessage(err, 'Unable to load ledger'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [editingLedgerId]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setSubmitting(true);
      setError('');

      const payload: LedgerCreate = {
        name: form.name.trim(),
        address: form.address.trim(),
        gst: form.gst.trim().toUpperCase(),
        opening_balance: form.opening_balance,
        phone_number: form.phone_number.trim(),
        email: form.email.trim(),
        website: form.website.trim(),
        bank_name: form.bank_name.trim(),
        branch_name: form.branch_name.trim(),
        account_name: form.account_name.trim(),
        account_number: form.account_number.trim(),
        ifsc_code: form.ifsc_code.trim().toUpperCase(),
      };

      if (editingLedgerId) {
        await api.put<Ledger>(`/ledgers/${editingLedgerId}`, payload);
        navigate('/ledgers', { state: { success: 'Ledger updated successfully.' } });
      } else {
        await api.post<Ledger>('/ledgers/', payload);
        navigate('/ledgers', { state: { success: 'Ledger created successfully.' } });
      }
    } catch (err) {
      setError(getApiErrorMessage(err, editingLedgerId ? 'Unable to update ledger' : 'Unable to create ledger'));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="page-grid">
        <section className="page-hero">
          <div>
            <p className="eyebrow">Ledgers</p>
            <h1 className="page-title">Loading ledger...</h1>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Ledgers</p>
          <h1 className="page-title">{editingLedgerId ? `Edit ledger #${editingLedgerId}` : 'Create ledger'}</h1>
          <p className="section-copy">{editingLedgerId ? 'Update ledger details below.' : 'Fill in the details to create a new ledger account.'}</p>
        </div>
      </section>

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <section className="content-grid">
        <article className="panel stack">
          <form className="stack" onSubmit={handleSubmit}>
            <div className="field-grid">
              <div className="field">
                <label htmlFor="ledger-name">Ledger name</label>
                <input
                  id="ledger-name"
                  className="input"
                  value={form.name}
                  onChange={(e) => setForm((c) => ({ ...c, name: e.target.value }))}
                  placeholder="Acme Traders"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="ledger-gst">GST</label>
                <input
                  id="ledger-gst"
                  className="input"
                  value={form.gst}
                  onChange={(e) => setForm((c) => ({ ...c, gst: e.target.value }))}
                  placeholder="27ABCDE1234F1Z5"
                  pattern="^$|[0-9]{2}[A-Za-z]{5}[0-9]{4}[A-Za-z][A-Za-z0-9]Z[A-Za-z0-9]$"
                  title="Enter a valid 15-character GSTIN (e.g. 27ABCDE1234F1Z5), or leave blank"
                  maxLength={15}
                />
                <small className="field-hint">Optional. If entered, format must be 27ABCDE1234F1Z5.</small>
              </div>
              <div className="field">
                <label htmlFor="ledger-phone">Phone number</label>
                <input
                  id="ledger-phone"
                  className="input"
                  value={form.phone_number}
                  onChange={(e) => setForm((c) => ({ ...c, phone_number: e.target.value }))}
                  placeholder="+91 9876543210"
                  required
                />
                <small className="field-hint">e.g. +91 98765 43210</small>
              </div>
              <div className="field">
                <label htmlFor="ledger-opening-balance">Opening balance</label>
                <input
                  id="ledger-opening-balance"
                  className="input"
                  type="number"
                  step="0.01"
                  value={form.opening_balance ?? ''}
                  onChange={(e) => setForm((c) => ({ ...c, opening_balance: e.target.value === '' ? null : (parseFloat(e.target.value) || null) }))}
                  placeholder="0.00"
                />
                <small className="field-hint">Positive for debit opening balance, negative for credit opening balance. Leave blank for none.</small>
              </div>
              <div className="field">
                <label htmlFor="ledger-email">Email</label>
                <input
                  id="ledger-email"
                  className="input"
                  value={form.email}
                  onChange={(e) => setForm((c) => ({ ...c, email: e.target.value }))}
                  placeholder="accounts@acme.com"
                />
              </div>
              <div className="field">
                <label htmlFor="ledger-website">Website</label>
                <input
                  id="ledger-website"
                  className="input"
                  value={form.website}
                  onChange={(e) => setForm((c) => ({ ...c, website: e.target.value }))}
                  placeholder="https://acme.com"
                />
              </div>
              <div className="field field--full">
                <label htmlFor="ledger-address">Address</label>
                <textarea
                  id="ledger-address"
                  className="textarea"
                  value={form.address}
                  onChange={(e) => setForm((c) => ({ ...c, address: e.target.value }))}
                  placeholder="221B Baker Street, London"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="ledger-bank-name">Bank name</label>
                <input
                  id="ledger-bank-name"
                  className="input"
                  value={form.bank_name}
                  onChange={(e) => setForm((c) => ({ ...c, bank_name: e.target.value }))}
                  placeholder="HDFC Bank"
                />
              </div>
              <div className="field">
                <label htmlFor="ledger-branch-name">Branch</label>
                <input
                  id="ledger-branch-name"
                  className="input"
                  value={form.branch_name}
                  onChange={(e) => setForm((c) => ({ ...c, branch_name: e.target.value }))}
                  placeholder="Bandra West"
                />
              </div>
              <div className="field">
                <label htmlFor="ledger-account-name">Account holder</label>
                <input
                  id="ledger-account-name"
                  className="input"
                  value={form.account_name}
                  onChange={(e) => setForm((c) => ({ ...c, account_name: e.target.value }))}
                  placeholder="Acme Traders"
                />
              </div>
              <div className="field">
                <label htmlFor="ledger-account-number">Account number</label>
                <input
                  id="ledger-account-number"
                  className="input"
                  value={form.account_number}
                  onChange={(e) => setForm((c) => ({ ...c, account_number: e.target.value }))}
                  placeholder="123456789012"
                />
              </div>
              <div className="field">
                <label htmlFor="ledger-ifsc">IFSC</label>
                <input
                  id="ledger-ifsc"
                  className="input"
                  value={form.ifsc_code}
                  onChange={(e) => setForm((c) => ({ ...c, ifsc_code: e.target.value }))}
                  placeholder="HDFC0001234"
                />
                <small className="field-hint">Format: SBIN0001234</small>
              </div>
            </div>

            <div className="button-row">
              <button type="button" className="button button--secondary" onClick={() => navigate('/ledgers')} title="Cancel and return to ledgers" aria-label="Cancel and return to ledgers">
                Cancel
              </button>
              <button className="button button--primary" disabled={submitting} title={editingLedgerId ? "Update ledger" : "Create ledger"} aria-label={editingLedgerId ? "Update ledger" : "Create ledger"}>
                {submitting
                  ? (editingLedgerId ? 'Updating ledger...' : 'Saving ledger...')
                  : (editingLedgerId ? 'Update ledger' : 'Create ledger')}
              </button>
            </div>
          </form>
        </article>
      </section>
    </div>
  );
}
