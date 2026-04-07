import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import { useEscapeClose } from '../hooks/useEscapeClose';
import type { ShortcutAction, ShortcutExecuteResponse } from '../types/api';

type ShortcutLauncherProps = {
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
};

export default function ShortcutLauncher({ onError, onSuccess }: ShortcutLauncherProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [shortcuts, setShortcuts] = useState<ShortcutAction[]>([]);
  const [executingKey, setExecutingKey] = useState('');
  const navigate = useNavigate();

  useEscapeClose(() => setOpen(false));

  useEffect(() => {
    if (!open || shortcuts.length > 0) {
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        const res = await api.get<ShortcutAction[]>('/shortcuts/');
        if (!cancelled) {
          setShortcuts(res.data);
        }
      } catch (err) {
        if (!cancelled) {
          onError(getApiErrorMessage(err, 'Unable to load shortcuts'));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, shortcuts.length, onError]);

  async function runShortcut(shortcut: ShortcutAction) {
    try {
      setExecutingKey(shortcut.key);
      const res = await api.post<ShortcutExecuteResponse>('/shortcuts/execute', { key: shortcut.key });
      if (res.data.path) {
        navigate(res.data.path);
      }
      onSuccess(res.data.message);
      setOpen(false);
    } catch (err) {
      onError(getApiErrorMessage(err, 'Unable to execute shortcut'));
    } finally {
      setExecutingKey('');
    }
  }

  return (
    <>
      <button
        type="button"
        className="button button--ghost"
        onClick={() => setOpen(true)}
        title="Open shortcuts"
        aria-label="Open shortcuts"
      >
        Shortcuts
      </button>

      {open ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title" onClick={() => setOpen(false)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '620px' }}>
            <div className="panel__header">
              <div>
                <p className="eyebrow">Quick actions</p>
                <h2 id="shortcuts-title" className="nav-panel__title">Shortcuts</h2>
              </div>
              <button type="button" className="button button--ghost" onClick={() => setOpen(false)} aria-label="Close shortcuts">
                ✕
              </button>
            </div>

            {loading ? (
              <div className="empty-state">Loading shortcuts...</div>
            ) : (
              <div className="stack">
                {shortcuts.map((shortcut) => (
                  <button
                    key={shortcut.key}
                    type="button"
                    className="nav-link"
                    onClick={() => void runShortcut(shortcut)}
                    disabled={executingKey === shortcut.key}
                    style={{ justifyContent: 'space-between' }}
                  >
                    <span>
                      <strong>{shortcut.label}</strong>
                      <span className="table-subtext" style={{ display: 'block' }}>{shortcut.description}</span>
                    </span>
                    <span className="status-chip">
                      {executingKey === shortcut.key ? 'Running' : shortcut.kind}
                    </span>
                  </button>
                ))}
                {!loading && shortcuts.length === 0 ? <div className="empty-state">No shortcuts available.</div> : null}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
