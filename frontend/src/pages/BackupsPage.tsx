import { useEffect, useMemo, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type {
  BackupCreateResponse,
  BackupPreflightResponse,
  BackupRestoreResponse,
  BackupSummary,
} from '../types/api';

function formatDate(value: string) {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function BackupsPage() {
  const [items, setItems] = useState<BackupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreDone, setRestoreDone] = useState(false);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [confirmText, setConfirmText] = useState('');
  const [preflight, setPreflight] = useState<BackupPreflightResponse | null>(null);

  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  async function loadBackups() {
    try {
      setLoading(true);
      const response = await api.get<BackupSummary[]>('/backups/');
      setItems(response.data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load backups'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadBackups();
  }, []);

  async function handleCreateBackup() {
    try {
      setCreating(true);
      setError('');
      const response = await api.post<BackupCreateResponse>('/backups/create', undefined, {
        timeout: 0,
      });
      setSuccess(`Backup created: ${response.data.file_name}`);
      await loadBackups();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to create backup'));
    } finally {
      setCreating(false);
    }
  }

  async function handleDownload(fileName: string) {
    try {
      setError('');
      const response = await api.get(`/backups/${encodeURIComponent(fileName)}/download`, {
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = fileName;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to download backup'));
    }
  }

  async function handlePreflight() {
    if (!selectedFile) {
      setError('Please choose a backup file first.');
      return;
    }

    const formData = new FormData();
    formData.append('backup_file', selectedFile);

    try {
      setError('');
      setPreflight(null);
      const response = await api.post<BackupPreflightResponse>('/backups/preflight', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 0,
      });
      setPreflight(response.data);
      if (!response.data.valid) {
        setError(response.data.reason || 'Backup is not compatible for restore.');
      }
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to preflight backup'));
    }
  }

  async function handleRestore() {
    if (!selectedFile) {
      setError('Please choose a backup file first.');
      return;
    }

    const formData = new FormData();
    formData.append('backup_file', selectedFile);
    formData.append('confirm_text', confirmText);

    try {
      setRestoring(true);
      setRestoreDone(false);
      setError('');
      const response = await api.post<BackupRestoreResponse>('/backups/restore', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 0,
      });
      setSuccess(`${response.data.detail}. Applied migrations: ${response.data.applied_migrations}`);
      setConfirmText('');
      setPreflight(null);
      setSelectedFile(null);
      await loadBackups();
      setRestoreDone(true);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to restore backup'));
    } finally {
      setRestoring(false);
    }
  }

  const canRestore = useMemo(() => {
    if (!preflight) return false;
    if (!preflight.valid) return false;
    return confirmText.trim().toUpperCase() === 'RESTORE';
  }, [confirmText, preflight]);

  const showRestoreDialog = restoring || restoreDone;

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Admin · Settings</p>
          <h1 className="page-title">Backups</h1>
          <p className="section-copy">Create encrypted backups and restore only encrypted backup files.</p>
        </div>
        <div className="button-row">
          <button className="button button--primary" onClick={() => void handleCreateBackup()} disabled={creating}>
            {creating ? 'Creating backup...' : 'Create backup'}
          </button>
        </div>
      </section>

      <StatusToasts
        success={success}
        error={error}
        onClearSuccess={() => setSuccess('')}
        onClearError={() => setError('')}
      />

      {showRestoreDialog && (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="restore-dialog-title"
          aria-live="assertive"
        >
          <div className="modal-panel restore-progress-panel" onClick={(e) => e.stopPropagation()}>
            {restoring ? (
              <>
                <div className="restore-progress-spinner" aria-hidden="true" />
                <h2 id="restore-dialog-title" className="nav-panel__title" style={{ marginBottom: '8px' }}>
                  Restore in progress
                </h2>
                <p className="muted-text" style={{ textAlign: 'center' }}>
                  Please do not close or refresh this window.
                </p>
                <p className="muted-text" style={{ textAlign: 'center', marginTop: '4px', fontSize: '0.8rem' }}>
                  This may take a moment&hellip;
                </p>
              </>
            ) : (
              <>
                <div className="restore-progress-icon" aria-hidden="true">✓</div>
                <h2 id="restore-dialog-title" className="nav-panel__title" style={{ marginBottom: '8px' }}>
                  Restore complete
                </h2>
                <p className="muted-text" style={{ textAlign: 'center' }}>
                  The database has been restored successfully.
                </p>
                <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'center' }}>
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={() => window.location.reload()}
                  >
                    Refresh page
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Available backups</p>
              <h2 className="nav-panel__title">Backup files</h2>
            </div>
          </div>

          {loading ? (
            <div className="empty-state">Loading backups...</div>
          ) : items.length === 0 ? (
            <div className="empty-state">No backups found.</div>
          ) : (
            <div className="table-list">
              {items.map((item) => (
                <div key={item.file_name} className="table-row">
                  <div className="table-row__meta">
                    <strong>{item.file_name}</strong>
                    <span className="table-subtext">
                      {formatDate(item.created_at)} · {formatSize(item.size_bytes)}
                    </span>
                    {item.migration_head ? (
                      <span className="table-subtext">Migration head: {item.migration_head}</span>
                    ) : null}
                  </div>
                  <div className="table-row__actions">
                    <button className="button button--ghost" onClick={() => void handleDownload(item.file_name)}>
                      Download
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Restore</p>
              <h2 className="nav-panel__title">Restore from backup archive</h2>
            </div>
          </div>

          <div className="field">
            <label htmlFor="restore-file">Encrypted backup (.enc)</label>
            <input
              id="restore-file"
              className="input"
              type="file"
              accept=".enc"
              onChange={(e) => {
                const file = e.target.files?.[0] || null;
                setSelectedFile(file);
                setPreflight(null);
              }}
            />
            <small className="field-hint">Upload only the encrypted .enc backup downloaded from this app.</small>
          </div>

          <div className="button-row">
            <button
              type="button"
              className="button button--secondary"
              disabled={!selectedFile || restoring}
              onClick={() => void handlePreflight()}
            >
              Check compatibility
            </button>
          </div>

          {preflight ? (
            <div className="summary-box">
              <p className="eyebrow">Preflight result</p>
              <p className="summary-box__value" style={{ fontSize: '1rem' }}>
                {preflight.compatibility}
              </p>
              {preflight.reason ? <p className="muted-text">{preflight.reason}</p> : null}
              {preflight.backup_created_at ? (
                <p className="muted-text">Backup created: {formatDate(preflight.backup_created_at)}</p>
              ) : null}
              {preflight.backup_migration_head ? (
                <p className="muted-text">Backup migration head: {preflight.backup_migration_head}</p>
              ) : null}
              {preflight.current_migration_head ? (
                <p className="muted-text">Current migration head: {preflight.current_migration_head}</p>
              ) : null}
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="restore-confirm">Type RESTORE to confirm</label>
            <input
              id="restore-confirm"
              className="input"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="RESTORE"
            />
          </div>

          <div className="button-row">
            <button
              type="button"
              className="button button--danger"
              disabled={!canRestore || restoring}
              onClick={() => void handleRestore()}
            >
              {restoring ? 'Restoring...' : 'Restore backup'}
            </button>
          </div>
        </article>
      </section>
    </div>
  );
}
