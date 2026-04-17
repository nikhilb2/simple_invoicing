import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import { useAuth } from '../context/AuthContext';
import { useFY } from '../context/FYContext';
import type { CompanyProfile, CompanyProfileUpdate, InvoiceSeries, InvoiceSeriesUpdate } from '../types/api';
import { isCompanyConfigured } from '../utils/companySetup';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const VOUCHER_LABELS: Record<string, string> = {
  sales: 'Sales',
  purchase: 'Purchase',
  payment: 'Payment',
};

function buildPreview(s: InvoiceSeriesUpdate, nextSeq: number, fyLabel?: string | null): string {
  const sep = s.separator ?? '-';
  const seq = String(nextSeq).padStart(s.pad_digits, '0');
  if (!s.include_year) {
    return `${s.prefix}${sep}${seq}${s.suffix}`;
  }
  const now = new Date();
  let yearPart: string;
  if (s.year_format === 'FY') {
    yearPart = fyLabel ?? 'FY';
  } else if (s.year_format === 'MM-YYYY') {
    yearPart = `${String(now.getMonth() + 1).padStart(2, '0')}${sep}${now.getFullYear()}`;
  } else {
    yearPart = `${now.getFullYear()}`;
  }
  return `${s.prefix}${sep}${yearPart}${sep}${seq}${s.suffix}`;
}

// ---------------------------------------------------------------------------
// InvoiceSeriesCard
// ---------------------------------------------------------------------------

type SeriesRowState = InvoiceSeriesUpdate;

function InvoiceSeriesCard({ sectionRef }: { sectionRef?: React.RefObject<HTMLElement> }) {
  const { activeFY } = useFY();
  const [seriesList, setSeriesList] = useState<InvoiceSeries[]>([]);
  const [drafts, setDrafts] = useState<Record<number, SeriesRowState>>({});
  const [saving, setSaving] = useState<Record<number, boolean>>({});
  const [rowError, setRowError] = useState<Record<number, string>>({});
  const [rowSuccess, setRowSuccess] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const saveInFlightRef = useRef<Record<number, boolean>>({});

  useEffect(() => {
    setLoading(true);
    void (async () => {
      try {
        const params: Record<string, string | number> = {};
        if (activeFY) params.financial_year_id = activeFY.id;
        const res = await api.get<InvoiceSeries[]>('/invoice-series/', { params });
        setSeriesList(res.data);
        const initial: Record<number, SeriesRowState> = {};
        for (const s of res.data) {
          initial[s.id] = {
            prefix: s.prefix,
            suffix: s.suffix,
            include_year: s.include_year,
            year_format: s.year_format,
            separator: s.separator,
            pad_digits: s.pad_digits,
          };
        }
        setDrafts(initial);
      } catch {
        // non-admin users won't see this card
      } finally {
        setLoading(false);
      }
    })();
  }, [activeFY?.id]);

  function patchDraft(id: number, patch: Partial<SeriesRowState>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function saveSeries(s: InvoiceSeries) {
    const draft = drafts[s.id];
    if (!draft) return;
    if (saveInFlightRef.current[s.id]) return;
    saveInFlightRef.current[s.id] = true;
    setSaving((prev) => ({ ...prev, [s.id]: true }));
    setRowError((prev) => ({ ...prev, [s.id]: '' }));
    setRowSuccess((prev) => ({ ...prev, [s.id]: '' }));
    try {
      const res = await api.put<InvoiceSeries>(`/invoice-series/${s.id}`, draft);
      setSeriesList((prev) => prev.map((x) => (x.id === s.id ? res.data : x)));
      setRowSuccess((prev) => ({ ...prev, [s.id]: 'Saved' }));
      setTimeout(() => setRowSuccess((prev) => ({ ...prev, [s.id]: '' })), 2500);
    } catch (err) {
      setRowError((prev) => ({ ...prev, [s.id]: getApiErrorMessage(err, 'Failed to save') }));
    } finally {
      saveInFlightRef.current[s.id] = false;
      setSaving((prev) => ({ ...prev, [s.id]: false }));
    }
  }

  if (loading) return <article className="panel stack"><div className="empty-state">Loading series…</div></article>;
  if (seriesList.length === 0) return null;

  return (
    <article className="panel stack" id="invoice-series-settings" ref={sectionRef} tabIndex={-1}>
      <div className="panel__header">
        <div>
          <p className="eyebrow">Numbering</p>
          <h2 className="nav-panel__title">
            Invoice series{activeFY ? ` — FY ${activeFY.label}` : ''}
          </h2>
        </div>
      </div>
      <p style={{ fontSize: '0.875rem', opacity: 0.7, marginBottom: '8px' }}>
        Configure the prefix, suffix, year, and sequence counter for each voucher type.
        Changes apply to the next invoice created — existing numbers are not affected.
      </p>

      <div className="stack" style={{ gap: '24px' }}>
        {seriesList.map((s) => {
          const draft = drafts[s.id];
          if (!draft) return null;
          const preview = buildPreview(draft, s.next_sequence, activeFY?.label);
          return (
            <div key={s.id} className="panel" style={{ padding: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                <strong style={{ textTransform: 'capitalize' }}>{VOUCHER_LABELS[s.voucher_type] ?? s.voucher_type}</strong>
                <span style={{ fontSize: '0.8rem', opacity: 0.6 }}>Next: #{s.next_sequence}</span>
              </div>

              <div className="field-grid">
                <div className="field">
                  <label htmlFor={`series-prefix-${s.id}`}>Prefix</label>
                  <input
                    id={`series-prefix-${s.id}`}
                    className="input"
                    value={draft.prefix}
                    onChange={(e) => patchDraft(s.id, { prefix: e.target.value.toUpperCase() })}
                    placeholder="INV"
                    style={{ textTransform: 'uppercase' }}
                  />
                </div>

                <div className="field">
                  <label htmlFor={`series-suffix-${s.id}`}>Suffix</label>
                  <input
                    id={`series-suffix-${s.id}`}
                    className="input"
                    value={draft.suffix}
                    onChange={(e) => patchDraft(s.id, { suffix: e.target.value.toUpperCase() })}
                    placeholder="/A"
                    style={{ textTransform: 'uppercase' }}
                  />
                </div>

                <div className="field">
                  <label htmlFor={`series-sep-${s.id}`}>Separator</label>
                  <input
                    id={`series-sep-${s.id}`}
                    className="input"
                    value={draft.separator}
                    maxLength={3}
                    onChange={(e) => patchDraft(s.id, { separator: e.target.value })}
                    placeholder="-"
                  />
                </div>

                <div className="field">
                  <label htmlFor={`series-pad-${s.id}`}>Pad digits</label>
                  <select
                    id={`series-pad-${s.id}`}
                    className="select"
                    value={draft.pad_digits}
                    onChange={(e) => patchDraft(s.id, { pad_digits: Number(e.target.value) as 2 | 3 | 4 })}
                  >
                    <option value={2}>2 (e.g. 01)</option>
                    <option value={3}>3 (e.g. 001)</option>
                    <option value={4}>4 (e.g. 0001)</option>
                  </select>
                </div>

                <div className="field">
                  <label htmlFor={`series-year-fmt-${s.id}`}>Year format</label>
                  <select
                    id={`series-year-fmt-${s.id}`}
                    className="select"
                    value={draft.year_format}
                    disabled={!draft.include_year}
                    onChange={(e) => patchDraft(s.id, { year_format: e.target.value as 'YYYY' | 'MM-YYYY' | 'FY' })}
                  >
                    <option value="YYYY">YYYY (e.g. 2026)</option>
                    <option value="MM-YYYY">MM-YYYY (e.g. 04-2026)</option>
                    <option value="FY">FY (e.g. 2025-26)</option>
                  </select>
                </div>

                <div className="field" style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingTop: '22px' }}>
                  <input
                    id={`series-include-year-${s.id}`}
                    type="checkbox"
                    checked={draft.include_year}
                    onChange={(e) => patchDraft(s.id, { include_year: e.target.checked })}
                  />
                  <label htmlFor={`series-include-year-${s.id}`} style={{ marginBottom: 0, cursor: 'pointer' }}>Include year</label>
                </div>
              </div>

              <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.875rem', opacity: 0.7 }}>
                  Preview: <strong>{preview}</strong>
                </span>
                <button
                  className="button button--primary"
                  style={{ marginTop: 0, padding: '6px 16px', fontSize: '0.875rem' }}
                  disabled={saving[s.id]}
                  onClick={() => void saveSeries(s)}
                >
                  {saving[s.id] ? 'Saving…' : 'Save'}
                </button>
                {rowSuccess[s.id] && <span style={{ color: 'var(--color-success, green)', fontSize: '0.875rem' }}>{rowSuccess[s.id]}</span>}
                {rowError[s.id] && <span style={{ color: 'var(--color-danger, red)', fontSize: '0.875rem' }}>{rowError[s.id]}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// CompanyPage
// ---------------------------------------------------------------------------

export default function CompanyPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isAdmin } = useAuth();
  const seriesSectionRef = useRef<HTMLElement>(null);
  const companySetupSectionRef = useRef<HTMLElement>(null);
  const [form, setForm] = useState<CompanyProfileUpdate>({
    name: '',
    address: '',
    gst: '',
    phone_number: '',
    currency_code: 'USD',
    email: '',
    website: '',
  });
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [initialSetupRequired, setInitialSetupRequired] = useState<boolean | null>(null);
  const [showFirstSetupPrompt, setShowFirstSetupPrompt] = useState(false);
  const setupRequiredByRoute = searchParams.get('setup') === 'required';
  const [showSetupDialog, setShowSetupDialog] = useState(setupRequiredByRoute);
  const [highlightCompanySetup, setHighlightCompanySetup] = useState(false);

  useEffect(() => {
    if (setupRequiredByRoute) {
      setShowSetupDialog(true);
    }
  }, [setupRequiredByRoute]);

  async function loadCompanyProfile() {
    try {
      setLoading(true);
      setError('');
      const response = await api.get<CompanyProfile>('/company/');
      if (initialSetupRequired === null) {
        setInitialSetupRequired(!isCompanyConfigured(response.data));
      }
      setForm({
        name: response.data.name || '',
        address: response.data.address || '',
        gst: response.data.gst || '',
        phone_number: response.data.phone_number || '',
        currency_code: response.data.currency_code || 'USD',
        email: response.data.email || '',
        website: response.data.website || '',
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
      };

      await api.put<CompanyProfile>('/company/', payload);
      setSuccess('Company profile saved. New invoices will now show this as billing company.');
      if (initialSetupRequired && payload.name) {
        setShowFirstSetupPrompt(true);
      }
      await loadCompanyProfile();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to save company profile'));
    } finally {
      setSubmitting(false);
    }
  }

  function handleAdjustInvoiceSeries() {
    setShowFirstSetupPrompt(false);
    const section = seriesSectionRef.current;
    if (section) {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
      section.focus();
    }
  }

  function handleSkipOnboardingStep() {
    setShowFirstSetupPrompt(false);
    navigate('/');
  }

  function dismissSetupDialog() {
    setShowSetupDialog(false);
    setHighlightCompanySetup(true);
    setTimeout(() => setHighlightCompanySetup(false), 2500);

    const section = companySetupSectionRef.current;
    if (section) {
      section.focus({ preventScroll: true });
    }

    if (setupRequiredByRoute) {
      navigate('/company', { replace: true });
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

      {showSetupDialog ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="setup-required-title">
          <div className="modal-panel">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Getting started</p>
                <h2 id="setup-required-title" className="nav-panel__title">Complete company setup to continue</h2>
              </div>
            </div>
            <p className="section-copy" style={{ marginTop: '8px' }}>
              Save your company details first. After saving, you can optionally adjust invoice numbering series.
            </p>
            <div className="button-row" style={{ marginTop: '16px' }}>
              <button
                type="button"
                className="button button--primary"
                onClick={dismissSetupDialog}
                title="Start company setup"
                aria-label="Start company setup"
              >
                Start setup
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showFirstSetupPrompt ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="company-created-title">
          <div className="modal-panel">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Next step</p>
                <h2 id="company-created-title" className="nav-panel__title">Company created successfully</h2>
              </div>
            </div>
            <p className="section-copy" style={{ marginTop: '8px' }}>
              {isAdmin
                ? 'You can now optionally adjust invoice series before creating invoices.'
                : 'Setup is complete. You can continue to dashboard now.'}
            </p>
            <div className="button-row" style={{ marginTop: '16px' }}>
              {isAdmin ? (
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={handleAdjustInvoiceSeries}
                  title="Adjust invoice series"
                  aria-label="Adjust invoice series"
                >
                  Adjust invoice series
                </button>
              ) : null}
              <button
                type="button"
                className="button button--ghost"
                onClick={handleSkipOnboardingStep}
                title="Skip for now"
                aria-label="Skip for now"
              >
                Skip for now
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <section className="content-grid">
        <article
          className="panel stack"
          ref={companySetupSectionRef}
          tabIndex={-1}
          style={highlightCompanySetup ? { borderColor: 'var(--color-primary)', boxShadow: '0 0 0 3px rgba(59, 130, 246, 0.25)' } : undefined}
        >
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

                <div className="field field--full">
                  <small className="field-hint">
                    Bank and cash account details are managed from Cash &amp; Bank Accounts.
                  </small>
                  <div className="button-row" style={{ marginTop: '8px' }}>
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={() => navigate('/cash-bank/accounts')}
                      title="Open Cash & Bank Accounts"
                      aria-label="Open Cash & Bank Accounts"
                    >
                      Manage cash &amp; bank accounts
                    </button>
                  </div>
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

        <InvoiceSeriesCard sectionRef={seriesSectionRef} />
      </section>
    </div>
  );
}
