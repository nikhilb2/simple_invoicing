import { useEffect, useRef, useState } from 'react';
import { Copy, Key, Plus, Trash2 } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import type { ApiKey, ApiKeyCreate, ApiKeyCreateResponse } from '../types/api';
import StatusToasts from '../components/StatusToasts';
import ConfirmDialog from '../components/ConfirmDialog';
import { useEscapeClose } from '../hooks/useEscapeClose';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function maxExpiryDate(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 1);
  return d.toISOString().split('T')[0];
}

function minExpiryDate(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split('T')[0];
}

function formatExpiry(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const expired = d < now;
  const label = d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  return expired ? `${label} (expired)` : label;
}

// ---------------------------------------------------------------------------
// Create modal
// ---------------------------------------------------------------------------

type CreateModalProps = {
  onClose: () => void;
  onCreated: (result: ApiKeyCreateResponse) => void;
};

function CreateModal({ onClose, onCreated }: CreateModalProps) {
  const [name, setName] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEscapeClose(onClose);
  useEffect(() => { nameRef.current?.focus(); }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !expiresAt) return;
    try {
      setSaving(true);
      setError(null);
      const payload: ApiKeyCreate = {
        name: name.trim(),
        expires_at: new Date(expiresAt).toISOString(),
      };
      const { data } = await api.post<ApiKeyCreateResponse>('/api-keys/', payload);
      onCreated(data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to create API key'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-api-key-title"
      onClick={onClose}
    >
      <div className="modal-panel" style={{ maxWidth: '440px' }} onClick={(e) => e.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">New API key</p>
            <h2 id="create-api-key-title" className="nav-panel__title">Create API key</h2>
          </div>
        </div>

        <form className="stack" onSubmit={handleSubmit} style={{ marginTop: '16px' }}>
          <div className="field">
            <label htmlFor="key-name">Key name</label>
            <input
              id="key-name"
              ref={nameRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. MCP Server"
              required
              maxLength={255}
            />
          </div>

          <div className="field">
            <label htmlFor="key-expires">Expires on</label>
            <input
              id="key-expires"
              type="date"
              value={expiresAt}
              min={minExpiryDate()}
              max={maxExpiryDate()}
              onChange={(e) => setExpiresAt(e.target.value)}
              required
            />
            <p style={{ fontSize: '0.78rem', opacity: 0.6, marginTop: '4px' }}>Maximum 1 year from today.</p>
          </div>

          {error && <p className="form-error">{error}</p>}

          <div className="form-actions">
            <button type="button" className="btn btn--ghost" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="btn btn--primary" disabled={saving || !name.trim() || !expiresAt}>
              {saving ? 'Creating…' : 'Create key'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Key reveal modal (shown once after creation)
// ---------------------------------------------------------------------------

type RevealModalProps = {
  rawKey: string;
  name: string;
  onClose: () => void;
};

function RevealModal({ rawKey, name, onClose }: RevealModalProps) {
  const [copied, setCopied] = useState(false);
  useEscapeClose(onClose);

  function copyKey() {
    navigator.clipboard.writeText(rawKey).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reveal-key-title"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="modal-panel" style={{ maxWidth: '520px' }}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">API key created</p>
            <h2 id="reveal-key-title" className="nav-panel__title">Copy your key now</h2>
          </div>
        </div>

        <p style={{ margin: '16px 0 8px', fontSize: '0.875rem', opacity: 0.75 }}>
          This is the only time <strong>{name}</strong> will be shown. Store it somewhere safe — it cannot be retrieved again.
        </p>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          background: 'var(--color-surface-2, #f4f4f5)',
          border: '1px solid var(--color-border, #e4e4e7)',
          borderRadius: '8px',
          padding: '10px 12px',
          fontFamily: 'monospace',
          fontSize: '0.82rem',
          wordBreak: 'break-all',
        }}>
          <span style={{ flex: 1 }}>{rawKey}</span>
          <button
            type="button"
            className="btn btn--ghost"
            style={{ flexShrink: 0, padding: '4px 8px' }}
            onClick={copyKey}
            title="Copy to clipboard"
          >
            <Copy size={14} />
            {copied ? ' Copied!' : ' Copy'}
          </button>
        </div>

        <div className="form-actions" style={{ marginTop: '20px' }}>
          <button type="button" className="btn btn--primary" onClick={onClose}>
            Done, I've saved it
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [revealKey, setRevealKey] = useState<ApiKeyCreateResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ApiKey | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [toast, setToast] = useState<{ kind: 'success' | 'error'; message: string } | null>(null);

  useEffect(() => { loadKeys(); }, []);

  async function loadKeys() {
    try {
      setLoading(true);
      const { data } = await api.get<ApiKey[]>('/api-keys/');
      setKeys(data);
    } catch (err) {
      setToast({ kind: 'error', message: getApiErrorMessage(err, 'Failed to load API keys') });
    } finally {
      setLoading(false);
    }
  }

  function handleCreated(result: ApiKeyCreateResponse) {
    setShowCreate(false);
    setRevealKey(result);
    setKeys((prev) => [result, ...prev]);
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      setDeleting(true);
      await api.delete(`/api-keys/${deleteTarget.id}`);
      setKeys((prev) => prev.filter((k) => k.id !== deleteTarget.id));
      setToast({ kind: 'success', message: `API key "${deleteTarget.name}" deleted.` });
    } catch (err) {
      setToast({ kind: 'error', message: getApiErrorMessage(err, 'Failed to delete API key') });
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  }

  const now = new Date();

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header__left">
          <h1 className="page-title">API Keys</h1>
          <p className="page-subtitle">Manage long-lived API keys for MCP server and integrations.</p>
        </div>
        <div className="page-header__actions">
          <button className="btn btn--primary" onClick={() => setShowCreate(true)}>
            <Plus size={16} />
            New API key
          </button>
        </div>
      </div>

      {loading ? (
        <p style={{ opacity: 0.5 }}>Loading…</p>
      ) : keys.length === 0 ? (
        <div className="empty-state">
          <Key size={32} opacity={0.3} />
          <p>No API keys yet. Create one to authenticate the MCP server.</p>
        </div>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Key prefix</th>
                <th>Expires</th>
                <th>Status</th>
                <th style={{ width: '48px' }} />
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => {
                const expired = new Date(k.expires_at) < now;
                return (
                  <tr key={k.id}>
                    <td>{k.name}</td>
                    <td>
                      <code style={{ fontFamily: 'monospace', fontSize: '0.82rem' }}>
                        {k.key_prefix}…
                      </code>
                    </td>
                    <td style={{ color: expired ? 'var(--color-danger, #ef4444)' : undefined }}>
                      {formatExpiry(k.expires_at)}
                    </td>
                    <td>
                      <span className={`badge ${expired ? 'badge--danger' : 'badge--success'}`}>
                        {expired ? 'Expired' : 'Active'}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn--ghost btn--icon"
                        title="Delete key"
                        onClick={() => setDeleteTarget(k)}
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <CreateModal onClose={() => setShowCreate(false)} onCreated={handleCreated} />
      )}

      {revealKey && (
        <RevealModal
          rawKey={revealKey.raw_key}
          name={revealKey.name}
          onClose={() => setRevealKey(null)}
        />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Delete API key"
          message={`Are you sure you want to delete "${deleteTarget.name}"? Any integrations using this key will stop working immediately.`}
          confirmText="Delete"
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
          danger
        />
      )}

      {toast && toast.kind === 'error' && (
        <StatusToasts
          error={toast.message}
          onClearError={() => setToast(null)}
          onClearSuccess={() => {}}
        />
      )}
      {toast && toast.kind === 'success' && (
        <StatusToasts
          success={toast.message}
          onClearError={() => {}}
          onClearSuccess={() => setToast(null)}
        />
      )}
    </div>
  );
}
