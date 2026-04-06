import { useEffect, useRef, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import type { SmtpConfig, SmtpConfigCreate, SmtpConfigUpdate } from '../types/api';
import StatusToasts from '../components/StatusToasts';
import ConfirmDialog from '../components/ConfirmDialog';
import { useEscapeClose } from '../hooks/useEscapeClose';

// ---------------------------------------------------------------------------
// Test email modal
// ---------------------------------------------------------------------------

type TestEmailModalProps = {
  config: SmtpConfig;
  onClose: () => void;
};

function TestEmailModal({ config, onClose }: TestEmailModalProps) {
  const [to, setTo] = useState('');
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ kind: 'success' | 'error'; message: string } | null>(null);
  useEscapeClose(onClose);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setSending(true);
      setResult(null);
      await api.post('/smtp-configs/test', { id: config.id, to: to.trim() });
      setResult({ kind: 'success', message: `Test email sent to ${to.trim()}.` });
    } catch (err) {
      setResult({ kind: 'error', message: getApiErrorMessage(err, 'Failed to send test email') });
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="test-email-title"
      onClick={onClose}
    >
      <div className="modal-panel" style={{ maxWidth: '420px' }} onClick={(e) => e.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Test connection</p>
            <h2 id="test-email-title" className="nav-panel__title">Send test email</h2>
          </div>
        </div>
        <p style={{ margin: '12px 0 4px', fontSize: '0.875rem', opacity: 0.7 }}>
          Using: <strong>{config.name}</strong> ({config.host}:{config.port})
        </p>
        <form className="stack" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="test-to">Recipient email</label>
            <input
              id="test-to"
              className="input"
              type="email"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder="you@example.com"
              required
              autoFocus
            />
          </div>
          {result && (
            <p
              role={result.kind === 'error' ? 'alert' : 'status'}
              style={{ color: result.kind === 'error' ? 'var(--color-error, #e53e3e)' : 'var(--color-success, #38a169)', fontSize: '0.875rem' }}
            >
              {result.message}
            </p>
          )}
          <div className="button-row" style={{ justifyContent: 'flex-end', gap: '12px' }}>
            <button type="button" className="button button--secondary" onClick={onClose}>
              Close
            </button>
            <button type="submit" className="button button--primary" disabled={sending}>
              {sending ? 'Sending…' : 'Send'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add / Edit modal
// ---------------------------------------------------------------------------

const EMPTY_FORM: SmtpConfigCreate = {
  name: '',
  host: '',
  port: 587,
  username: '',
  password: '',
  from_email: '',
  from_name: '',
  use_tls: true,
};

type SmtpFormModalProps = {
  editing: SmtpConfig | null;
  onClose: () => void;
  onSaved: (message: string) => void;
  onError: (message: string) => void;
};

function SmtpFormModal({ editing, onClose, onSaved, onError }: SmtpFormModalProps) {
  const [form, setForm] = useState<SmtpConfigCreate>(
    editing
      ? {
          name: editing.name,
          host: editing.host,
          port: editing.port,
          username: editing.username,
          password: '',
          from_email: editing.from_email,
          from_name: editing.from_name,
          use_tls: editing.use_tls,
        }
      : EMPTY_FORM
  );
  const [submitting, setSubmitting] = useState(false);
  const firstFieldRef = useRef<HTMLInputElement>(null);
  useEscapeClose(onClose);

  useEffect(() => {
    firstFieldRef.current?.focus();
  }, []);

  function set(field: keyof SmtpConfigCreate, value: string | number | boolean) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setSubmitting(true);
      if (editing) {
        const payload: SmtpConfigUpdate = {
          name: form.name.trim(),
          host: form.host.trim(),
          port: form.port,
          username: form.username.trim(),
          from_email: form.from_email.trim(),
          from_name: form.from_name.trim(),
          use_tls: form.use_tls,
        };
        if (form.password) {
          payload.password = form.password;
        }
        await api.put<SmtpConfig>(`/smtp-configs/${editing.id}`, payload);
        onSaved('SMTP configuration updated.');
      } else {
        await api.post<SmtpConfig>('/smtp-configs/', form);
        onSaved('SMTP configuration created.');
      }
      onClose();
    } catch (err) {
      onError(getApiErrorMessage(err, editing ? 'Unable to update configuration' : 'Unable to create configuration'));
    } finally {
      setSubmitting(false);
    }
  }

  const title = editing ? `Edit — ${editing.name}` : 'New SMTP configuration';

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="smtp-form-title"
      onClick={onClose}
    >
      <div
        className="modal-panel"
        style={{ maxWidth: '560px', width: '100%' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel__header">
          <div>
            <p className="eyebrow">{editing ? 'Edit config' : 'Add config'}</p>
            <h2 id="smtp-form-title" className="nav-panel__title">{title}</h2>
          </div>
        </div>

        <form className="stack" onSubmit={handleSubmit} style={{ marginTop: '16px' }}>
          <div className="field-grid">
            <div className="field">
              <label htmlFor="smtp-name">Name</label>
              <input
                ref={firstFieldRef}
                id="smtp-name"
                className="input"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="Gmail production"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="smtp-host">Host</label>
              <input
                id="smtp-host"
                className="input"
                value={form.host}
                onChange={(e) => set('host', e.target.value)}
                placeholder="smtp.gmail.com"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="smtp-port">Port</label>
              <input
                id="smtp-port"
                className="input"
                type="number"
                min={1}
                max={65535}
                value={form.port}
                onChange={(e) => set('port', Number(e.target.value))}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="smtp-username">Username</label>
              <input
                id="smtp-username"
                className="input"
                type="email"
                value={form.username}
                onChange={(e) => set('username', e.target.value)}
                placeholder="user@gmail.com"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="smtp-password">
                Password{editing ? ' (leave blank to keep current)' : ''}
              </label>
              <input
                id="smtp-password"
                className="input"
                type="password"
                value={form.password}
                onChange={(e) => set('password', e.target.value)}
                placeholder={editing ? '••••••••' : ''}
                required={!editing}
                autoComplete="new-password"
              />
            </div>
            <div className="field">
              <label htmlFor="smtp-from-email">From email</label>
              <input
                id="smtp-from-email"
                className="input"
                type="email"
                value={form.from_email}
                onChange={(e) => set('from_email', e.target.value)}
                placeholder="billing@yourcompany.com"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="smtp-from-name">From name</label>
              <input
                id="smtp-from-name"
                className="input"
                value={form.from_name}
                onChange={(e) => set('from_name', e.target.value)}
                placeholder="Your Company Billing"
                required
              />
            </div>
          </div>

          <label className="field" style={{ flexDirection: 'row', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={form.use_tls}
              onChange={(e) => set('use_tls', e.target.checked)}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            <span>Use TLS (STARTTLS)</span>
          </label>

          <div className="button-row" style={{ justifyContent: 'flex-end', gap: '12px' }}>
            <button type="button" className="button button--secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="button button--primary" disabled={submitting}>
              {submitting ? 'Saving…' : editing ? 'Save changes' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function SmtpSettingsPage() {
  const [configs, setConfigs] = useState<SmtpConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [showForm, setShowForm] = useState(false);
  const [editingConfig, setEditingConfig] = useState<SmtpConfig | null>(null);

  const [testingConfig, setTestingConfig] = useState<SmtpConfig | null>(null);

  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [activatingId, setActivatingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  async function loadConfigs() {
    try {
      setLoading(true);
      setError('');
      const res = await api.get<SmtpConfig[]>('/smtp-configs/');
      setConfigs(res.data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load SMTP configurations'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadConfigs();
  }, []);

  function openAdd() {
    setEditingConfig(null);
    setShowForm(true);
  }

  function openEdit(config: SmtpConfig) {
    setEditingConfig(config);
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingConfig(null);
  }

  function handleSaved(message: string) {
    setSuccess(message);
    void loadConfigs();
  }

  function handleFormError(message: string) {
    setError(message);
  }

  async function handleActivate(config: SmtpConfig) {
    try {
      setActivatingId(config.id);
      setError('');
      await api.post<SmtpConfig>(`/smtp-configs/${config.id}/activate`);
      setSuccess(`"${config.name}" is now the active SMTP configuration.`);
      await loadConfigs();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to activate configuration'));
    } finally {
      setActivatingId(null);
    }
  }

  async function confirmDelete() {
    if (pendingDeleteId === null) return;
    const id = pendingDeleteId;
    setPendingDeleteId(null);
    try {
      setDeletingId(id);
      setError('');
      await api.delete(`/smtp-configs/${id}`);
      setSuccess('SMTP configuration deleted.');
      await loadConfigs();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to delete configuration'));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Admin · Settings</p>
          <h1 className="page-title">SMTP settings</h1>
          <p className="section-copy">Manage outgoing email configurations used for invoices, statements, and reminders.</p>
        </div>
        <button className="button button--primary" onClick={openAdd}>
          Add configuration
        </button>
      </section>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      {loading ? (
        <p style={{ opacity: 0.6 }}>Loading…</p>
      ) : configs.length === 0 ? (
        <div className="panel stack" style={{ textAlign: 'center', padding: '40px' }}>
          <p className="eyebrow">No configurations</p>
          <p style={{ opacity: 0.7 }}>Add an SMTP configuration to enable outgoing email.</p>
          <button className="button button--primary" style={{ alignSelf: 'center', marginTop: '8px' }} onClick={openAdd}>
            Add first configuration
          </button>
        </div>
      ) : (
        <div className="stack" style={{ gap: '12px' }}>
          {configs.map((config) => (
            <article key={config.id} className="panel" style={{ padding: '20px 24px' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <strong style={{ fontSize: '1rem' }}>{config.name}</strong>
                      <span
                        style={{
                          display: 'inline-block',
                          padding: '2px 8px',
                          borderRadius: '999px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          background: config.is_active ? 'var(--color-success-bg, #c6f6d5)' : 'var(--color-muted-bg, #edf2f7)',
                          color: config.is_active ? 'var(--color-success-text, #22543d)' : 'var(--color-muted-text, #4a5568)',
                        }}
                      >
                        {config.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                    <p style={{ fontSize: '0.875rem', opacity: 0.65, marginTop: '2px' }}>
                      {config.host}:{config.port} · {config.from_email}
                      {config.use_tls ? ' · TLS' : ' · No TLS'}
                    </p>
                  </div>
                </div>

                <div className="button-row" style={{ gap: '8px', flexShrink: 0 }}>
                  {!config.is_active && (
                    <button
                      className="button button--secondary"
                      onClick={() => void handleActivate(config)}
                      disabled={activatingId === config.id}
                      title="Set as active configuration"
                    >
                      {activatingId === config.id ? 'Activating…' : 'Set active'}
                    </button>
                  )}
                  <button
                    className="button button--secondary"
                    onClick={() => setTestingConfig(config)}
                    title="Send a test email"
                  >
                    Test email
                  </button>
                  <button
                    className="button button--secondary"
                    onClick={() => openEdit(config)}
                    title="Edit this configuration"
                  >
                    Edit
                  </button>
                  <button
                    className="button button--danger"
                    onClick={() => setPendingDeleteId(config.id)}
                    disabled={deletingId === config.id || config.is_active}
                    title={config.is_active ? 'Cannot delete active configuration' : 'Delete this configuration'}
                  >
                    {deletingId === config.id ? 'Deleting…' : 'Delete'}
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {showForm && (
        <SmtpFormModal
          editing={editingConfig}
          onClose={closeForm}
          onSaved={handleSaved}
          onError={handleFormError}
        />
      )}

      {testingConfig && (
        <TestEmailModal
          config={testingConfig}
          onClose={() => setTestingConfig(null)}
        />
      )}

      {pendingDeleteId !== null && (
        <ConfirmDialog
          title="Delete SMTP configuration"
          message="This configuration will be permanently removed. This cannot be undone."
          confirmText="Delete"
          danger
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDeleteId(null)}
        />
      )}
    </div>
  );
}
