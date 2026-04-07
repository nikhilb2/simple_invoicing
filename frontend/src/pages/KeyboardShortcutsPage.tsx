import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import { useShortcuts } from '../context/ShortcutsContext';
import { ACTION_KEYS, ACTION_LABELS, DEFAULT_SHORTCUTS, type ActionKey } from '../utils/shortcutDefaults';
import StatusToasts from '../components/StatusToasts';
import ConfirmDialog from '../components/ConfirmDialog';

// Keys that should be ignored when recording (lone modifiers / lock keys)
const MODIFIER_KEYS = new Set([
  'Control', 'Shift', 'Alt', 'Meta',
  'CapsLock', 'NumLock', 'ScrollLock', 'Tab',
]);

function normalizeCombo(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey) parts.push('Ctrl');
  if (e.shiftKey) parts.push('Shift');
  if (e.altKey) parts.push('Alt');
  if (e.metaKey) parts.push('Meta');
  const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  parts.push(key);
  return parts.join('+');
}

export default function KeyboardShortcutsPage() {
  const { shortcutsMap, refetchShortcuts } = useShortcuts();

  // Maps action key → pending (recorded but not yet saved) shortcut string
  const [pending, setPending] = useState<Partial<Record<ActionKey, string>>>({});
  // Which row is currently in recording mode
  const [recording, setRecording] = useState<ActionKey | null>(null);
  // Per-row loading states
  const [savingKey, setSavingKey] = useState<ActionKey | null>(null);
  const [resettingKey, setResettingKey] = useState<ActionKey | null>(null);
  const [resettingAll, setResettingAll] = useState(false);
  // UI state
  const [showResetAllDialog, setShowResetAllDialog] = useState(false);
  const [success, setSuccess] = useState<string | undefined>();
  const [error, setError] = useState<string | undefined>();

  // Capture keydown in capture phase so it fires before other listeners
  useEffect(() => {
    if (!recording) return;

    function handleKeyDown(e: KeyboardEvent) {
      e.preventDefault();
      e.stopPropagation();

      if (e.key === 'Escape') {
        setRecording(null);
        return;
      }

      // Ignore lone modifier / lock keys
      if (MODIFIER_KEYS.has(e.key)) return;

      const combo = normalizeCombo(e);
      setPending((prev) => ({ ...prev, [recording!]: combo }));
      setRecording(null);
    }

    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [recording]);

  // Returns the action key that already owns the given combo (excluding the
  // row being edited), or null if there is no conflict.
  function getConflict(actionKey: ActionKey, combo: string): ActionKey | null {
    for (const key of ACTION_KEYS) {
      if (key === actionKey) continue;
      const current = pending[key] ?? shortcutsMap[key];
      if (current === combo) return key;
    }
    return null;
  }

  async function handleSave(actionKey: ActionKey) {
    const shortcutKey = pending[actionKey];
    if (!shortcutKey) return;
    setSavingKey(actionKey);
    try {
      await api.put(`/shortcuts/${actionKey}`, { shortcut_key: shortcutKey });
      await refetchShortcuts();
      setPending((prev) => {
        const next = { ...prev };
        delete next[actionKey];
        return next;
      });
      setSuccess('Shortcut saved.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to save shortcut'));
    } finally {
      setSavingKey(null);
    }
  }

  async function handleReset(actionKey: ActionKey) {
    setResettingKey(actionKey);
    try {
      await api.delete(`/shortcuts/${actionKey}`);
      await refetchShortcuts();
      setPending((prev) => {
        const next = { ...prev };
        delete next[actionKey];
        return next;
      });
      setSuccess('Shortcut reset to default.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to reset shortcut'));
    } finally {
      setResettingKey(null);
    }
  }

  async function handleResetAll() {
    setShowResetAllDialog(false);
    setResettingAll(true);
    try {
      await api.delete('/shortcuts/');
      await refetchShortcuts();
      setPending({});
      setSuccess('All shortcuts reset to defaults.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to reset all shortcuts'));
    } finally {
      setResettingAll(false);
    }
  }

  return (
    <div className="page-grid">
      {showResetAllDialog && (
        <ConfirmDialog
          title="Reset all shortcuts"
          message="This will reset all keyboard shortcuts to their defaults. Continue?"
          confirmText="Reset All"
          onConfirm={() => void handleResetAll()}
          onCancel={() => setShowResetAllDialog(false)}
          danger
        />
      )}

      <StatusToasts
        success={success}
        error={error}
        onClearSuccess={() => setSuccess(undefined)}
        onClearError={() => setError(undefined)}
      />

      <section className="page-hero">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page-title">Keyboard Shortcuts</h1>
          <p className="section-copy">Customise keyboard shortcuts to match your workflow.</p>
        </div>
        <button
          type="button"
          className="button button--secondary"
          onClick={() => setShowResetAllDialog(true)}
          disabled={resettingAll}
        >
          {resettingAll ? 'Resetting…' : 'Reset All to Defaults'}
        </button>
      </section>

      <section className="section-card">
        <table className="table" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th>Action</th>
              <th>Default Shortcut</th>
              <th>Your Shortcut</th>
              <th style={{ width: '160px' }} />
            </tr>
          </thead>
          <tbody>
            {ACTION_KEYS.map((key) => {
              const isRecording = recording === key;
              const pendingValue = pending[key];
              const displayValue = pendingValue ?? shortcutsMap[key];
              const conflict = pendingValue !== undefined ? getConflict(key, pendingValue) : null;
              const hasChange = pendingValue !== undefined;
              const isSaving = savingKey === key;
              const isResetting = resettingKey === key;

              return (
                <tr key={key}>
                  <td>{ACTION_LABELS[key]}</td>
                  <td>
                    <kbd>{DEFAULT_SHORTCUTS[key]}</kbd>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="input"
                      style={{
                        cursor: 'pointer',
                        textAlign: 'left',
                        fontFamily: 'monospace',
                        width: '100%',
                        maxWidth: '200px',
                        background: isRecording
                          ? 'var(--color-focus-ring, rgba(59,130,246,0.15))'
                          : conflict !== null
                            ? 'var(--color-error-bg, rgba(229,62,62,0.08))'
                            : undefined,
                      }}
                      onClick={() => setRecording(isRecording ? null : key)}
                      title={
                        isRecording
                          ? 'Press a key combination, or Escape to cancel'
                          : 'Click to record a new shortcut'
                      }
                      aria-label={
                        isRecording
                          ? 'Recording shortcut — press a key combination'
                          : `Current shortcut: ${displayValue}`
                      }
                    >
                      {isRecording ? 'Press keys…' : displayValue}
                    </button>
                    {conflict !== null && (
                      <p
                        role="alert"
                        style={{
                          color: 'var(--color-error, #e53e3e)',
                          fontSize: '0.75rem',
                          marginTop: '4px',
                        }}
                      >
                        Already used by: {ACTION_LABELS[conflict]}
                      </p>
                    )}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      {hasChange && conflict === null && (
                        <button
                          type="button"
                          className="button button--primary"
                          onClick={() => void handleSave(key)}
                          disabled={isSaving}
                          style={{ padding: '4px 12px', fontSize: '0.8125rem' }}
                        >
                          {isSaving ? 'Saving…' : 'Save'}
                        </button>
                      )}
                      <button
                        type="button"
                        className="button button--secondary"
                        onClick={() => void handleReset(key)}
                        disabled={isResetting || resettingAll}
                        style={{ padding: '4px 12px', fontSize: '0.8125rem' }}
                      >
                        {isResetting ? 'Resetting…' : 'Reset'}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
