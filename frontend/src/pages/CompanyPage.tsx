import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type { CompanyProfile, CompanyProfileUpdate } from '../types/api';

export default function CompanyPage() {
  const [form, setForm] = useState<CompanyProfileUpdate>({
    name: '',
    address: '',
    gst: '',
    phone_number: '',
    currency_code: 'USD',
    email: '',
    website: '',
    bank_name: '',
    branch_name: '',
    account_name: '',
    account_number: '',
    ifsc_code: '',
  });
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  async function loadCompanyProfile() {
    try {
      setLoading(true);
      setError('');
      const response = await api.get<CompanyProfile>('/company/');
      setForm({
        name: response.data.name || '',
        address: response.data.address || '',
        gst: response.data.gst || '',
        phone_number: response.data.phone_number || '',
        currency_code: response.data.currency_code || 'USD',
        email: response.data.email || '',
        website: response.data.website || '',
        bank_name: response.data.bank_name || '',
        branch_name: response.data.branch_name || '',
        account_name: response.data.account_name || '',
        account_number: response.data.account_number || '',
        ifsc_code: response.data.ifsc_code || '',
      });
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load company profile'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCompanyProfile();
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setSubmitting(true);
      setError('');
      setSuccess('');

      const payload: CompanyProfileUpdate = {
        name: form.name.trim(),
        address: form.address.trim(),
        gst: form.gst.trim().toUpperCase(),
        phone_number: form.phone_number.trim(),
        currency_code: form.currency_code.trim().toUpperCase(),
        email: form.email.trim(),
        website: form.website.trim(),
        bank_name: form.bank_name.trim(),
        branch_name: form.branch_name.trim(),
        account_name: form.account_name.trim(),
        account_number: form.account_number.trim(),
        ifsc_code: form.ifsc_code.trim().toUpperCase(),
      };

      await api.put<CompanyProfile>('/company/', payload);
      setSuccess('Company profile saved. New invoices will now show this as billing company.');
      await loadCompanyProfile();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to save company profile'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Company</p>
          <h1 className="page-title">Billing identity</h1>
          <p className="section-copy">Set the company details that appear as the billing party on all new invoices.</p>
        </div>
      </section>

      <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Company setup</p>
              <h2 className="nav-panel__title">Invoice header details</h2>
            </div>
          </div>

          {loading ? <div className="empty-state">Loading company profile...</div> : null}

          {!loading ? (
            <form className="stack" onSubmit={handleSubmit}>
              <div className="field-grid">
                <div className="field">
                  <label htmlFor="company-name">Company name</label>
                  <input
                    id="company-name"
                    className="input"
                    value={form.name}
                    onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                    placeholder="Simple Invoicing Pvt Ltd"
                    required
                  />
                </div>

                <div className="field">
                  <label htmlFor="company-gst">GST</label>
                  <input
                    id="company-gst"
                    className="input"
                    value={form.gst}
                    onChange={(event) => setForm((current) => ({ ...current, gst: event.target.value }))}
                    placeholder="27ABCDE1234F1Z5"
                  />
                  <small className="field-hint">Format: 27ABCDE1234F1Z5</small>
                </div>

                <div className="field">
                  <label htmlFor="company-phone">Phone number</label>
                  <input
                    id="company-phone"
                    className="input"
                    value={form.phone_number}
                    onChange={(event) => setForm((current) => ({ ...current, phone_number: event.target.value }))}
                    placeholder="+91 9876543210"
                  />
                  <small className="field-hint">e.g. +91 98765 43210</small>
                </div>

                <div className="field">
                  <label htmlFor="company-currency">Currency</label>
                  <select
                    id="company-currency"
                    className="select"
                    value={form.currency_code}
                    onChange={(event) => setForm((current) => ({ ...current, currency_code: event.target.value }))}
                  >
                    <option value="USD">USD - US Dollar</option>
                    <option value="INR">INR - Indian Rupee</option>
                    <option value="EUR">EUR - Euro</option>
                    <option value="GBP">GBP - British Pound</option>
                    <option value="AED">AED - UAE Dirham</option>
                  </select>
                </div>

                <div className="field">
                  <label htmlFor="company-email">Email</label>
                  <input
                    id="company-email"
                    className="input"
                    value={form.email}
                    onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                    placeholder="billing@simple.dev"
                  />
                </div>

                <div className="field">
                  <label htmlFor="company-website">Website</label>
                  <input
                    id="company-website"
                    className="input"
                    value={form.website}
                    onChange={(event) => setForm((current) => ({ ...current, website: event.target.value }))}
                    placeholder="https://simple.dev"
                  />
                </div>

                <div className="field field--full">
                  <label htmlFor="company-address">Address</label>
                  <textarea
                    id="company-address"
                    className="textarea"
                    value={form.address}
                    onChange={(event) => setForm((current) => ({ ...current, address: event.target.value }))}
                    placeholder="221B Baker Street, London"
                    required
                  />
                </div>

                <div className="field">
                  <label htmlFor="company-bank-name">Bank name</label>
                  <input
                    id="company-bank-name"
                    className="input"
                    value={form.bank_name}
                    onChange={(event) => setForm((current) => ({ ...current, bank_name: event.target.value }))}
                    placeholder="HDFC Bank"
                  />
                </div>

                <div className="field">
                  <label htmlFor="company-branch-name">Branch</label>
                  <input
                    id="company-branch-name"
                    className="input"
                    value={form.branch_name}
                    onChange={(event) => setForm((current) => ({ ...current, branch_name: event.target.value }))}
                    placeholder="Bandra West"
                  />
                </div>

                <div className="field">
                  <label htmlFor="company-account-name">Account holder name</label>
                  <input
                    id="company-account-name"
                    className="input"
                    value={form.account_name}
                    onChange={(event) => setForm((current) => ({ ...current, account_name: event.target.value }))}
                    placeholder="Simple Invoicing Pvt Ltd"
                  />
                </div>

                <div className="field">
                  <label htmlFor="company-account-number">Account number</label>
                  <input
                    id="company-account-number"
                    className="input"
                    value={form.account_number}
                    onChange={(event) => setForm((current) => ({ ...current, account_number: event.target.value }))}
                    placeholder="123456789012"
                  />
                </div>

                <div className="field">
                  <label htmlFor="company-ifsc">IFSC</label>
                  <input
                    id="company-ifsc"
                    className="input"
                    value={form.ifsc_code}
                    onChange={(event) => setForm((current) => ({ ...current, ifsc_code: event.target.value }))}
                    placeholder="HDFC0001234"
                  />
                  <small className="field-hint">Format: SBIN0001234</small>
                </div>
              </div>

              <div className="button-row">
                <button className="button button--primary" disabled={submitting} title="Save company details" aria-label="Save company details">
                  {submitting ? 'Saving company...' : 'Save company details'}
                </button>
              </div>
            </form>
          ) : null}
        </article>
      </section>
    </div>
  );
}
