import { useEffect, useState } from 'react';
import type { KeyboardEvent } from 'react';
import {
  bindingToDisplay,
  defaultShortcutPreferences,
  loadCustomShortcuts,
  loadShortcutPreferences,
  matchesBinding,
  saveShortcutPreferences,
  saveCustomShortcuts,
  type CustomShortcut,
  type ShortcutAction,
  shortcutActionLabels,
  type ShortcutPreferences,
} from '../utils/shortcutPreferences';

const shortcutActions: ShortcutAction[] = [
  'submit_invoice',
  'add_line_item',
  'add_ledger',
  'add_product',
  'update_stock',
  'toggle_help',
];

const pageOptions = [
  { label: 'Overview', value: '/' },
  { label: 'Products', value: '/products' },
  { label: 'Inventory', value: '/inventory' },
  { label: 'Ledgers', value: '/ledgers' },
  { label: 'Day Book', value: '/day-book' },
  { label: 'Invoices', value: '/invoices' },
  { label: 'Company', value: '/company' },
  { label: 'Keyboard Shortcuts', value: '/keyboard-shortcuts' },
  { label: 'SMTP Settings', value: '/smtp-settings' },
];

export default function KeyboardShortcutsPage() {
  const [preferences, setPreferences] = useState<ShortcutPreferences>(defaultShortcutPreferences);
  const [customShortcuts, setCustomShortcuts] = useState<CustomShortcut[]>([]);
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [customTitle, setCustomTitle] = useState('');
  const [customPage, setCustomPage] = useState('/');
  const [customRecording, setCustomRecording] = useState(false);
  const [customBinding, setCustomBinding] = useState(defaultShortcutPreferences.submit_invoice);
  const [recordingAction, setRecordingAction] = useState<ShortcutAction | null>(null);

  useEffect(() => {
    setPreferences(loadShortcutPreferences());
    setCustomShortcuts(loadCustomShortcuts());
  }, []);

  function updateBinding(action: ShortcutAction, updates: Partial<ShortcutPreferences[ShortcutAction]>) {
    setPreferences((current) => ({
      ...current,
      [action]: { ...current[action], ...updates },
    }));
  }

  function handleSave() {
    saveShortcutPreferences(preferences);
  }

  function handleReset() {
    setPreferences(defaultShortcutPreferences);
    saveShortcutPreferences(defaultShortcutPreferences);
  }

  function captureBinding(action: ShortcutAction, event: KeyboardEvent<HTMLElement>) {
    const key = event.key;
    const isModifierOnly = ['Shift', 'Control', 'Alt', 'Meta'].includes(key);

    event.preventDefault();

    if (key === 'Escape') {
      setRecordingAction(null);
      return;
    }

    if (isModifierOnly) {
      return;
    }

    const binding = {
      ctrlOrCmd: event.ctrlKey || event.metaKey,
      shift: event.shiftKey,
      alt: event.altKey,
      key: key.length === 1 ? key.toUpperCase() : key,
    };

    updateBinding(action, binding);
    setRecordingAction(null);
  }

  function captureCustomBinding(event: KeyboardEvent<HTMLElement>) {
    const key = event.key;
    const isModifierOnly = ['Shift', 'Control', 'Alt', 'Meta'].includes(key);

    event.preventDefault();

    if (key === 'Escape') {
      setCustomRecording(false);
      return;
    }

    if (isModifierOnly) {
      return;
    }

    setCustomBinding({
      ctrlOrCmd: event.ctrlKey || event.metaKey,
      shift: event.shiftKey,
      alt: event.altKey,
      key: key.length === 1 ? key.toUpperCase() : key,
    });
    setCustomRecording(false);
  }

  function handleSaveCustomShortcut() {
    if (!customTitle.trim()) {
      return;
    }

    const nextShortcut: CustomShortcut = {
      id: `${Date.now()}`,
      title: customTitle.trim(),
      page: customPage.trim() || '/',
      binding: customBinding,
    };

    const nextShortcuts = [...customShortcuts, nextShortcut];
    setCustomShortcuts(nextShortcuts);
    saveCustomShortcuts(nextShortcuts);
    setCustomTitle('');
    setCustomPage('/');
    setCustomBinding(defaultShortcutPreferences.submit_invoice);
    setCustomRecording(false);
    setShowCustomForm(false);
  }

  function handleDeleteCustomShortcut(id: string) {
    const nextShortcuts = customShortcuts.filter((shortcut) => shortcut.id !== id);
    setCustomShortcuts(nextShortcuts);
    saveCustomShortcuts(nextShortcuts);
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Navigation</p>
          <h1 className="page-title">Keyboard shortcuts</h1>
          <p className="section-copy">Fast actions available in the invoice composer and supporting modals. You can edit them below.</p>
        </div>
      </section>

      <section className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Quick access</p>
            <h2 className="nav-panel__title">Shortcut preferences</h2>
          </div>
          <div className="button-row">
            <button type="button" className="button button--secondary" onClick={handleReset}>
              Reset defaults
            </button>
            <button type="button" className="button button--primary" onClick={handleSave}>
              Save shortcuts
            </button>
          </div>
        </div>

        <div className="shortcut-list">
          {shortcutActions.map((action) => {
            const binding = preferences[action];
            return (
              <div key={action} className="shortcut-edit-row">
                <strong>{shortcutActionLabels[action]}</strong>
                <button
                  type="button"
                  className="input shortcut-capture-button"
                  onClick={() => setRecordingAction(action)}
                  onKeyDown={(event) => {
                    if (recordingAction === action || document.activeElement === event.currentTarget) {
                      captureBinding(action, event);
                    }
                  }}
                  aria-label={`Capture shortcut for ${shortcutActionLabels[action]}`}
                >
                  {recordingAction === action ? 'Press a shortcut...' : bindingToDisplay(binding)}
                </button>
                <span className="field-hint">{recordingAction === action ? 'Waiting for key press' : 'Click and press the new shortcut'}</span>
              </div>
            );
          })}
        </div>

        <div className="field-hint">
          Changes are stored locally in this browser. The composer will use the saved shortcuts after you refresh or revisit the page.
        </div>
      </section>

      <section className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Pages</p>
            <h2 className="nav-panel__title">Page shortcuts</h2>
          </div>
          <button type="button" className="button button--primary" onClick={() => setShowCustomForm(true)}>
            Add shortcut
          </button>
        </div>

        <div className="shortcut-list">
          {customShortcuts.map((shortcut) => (
            <div key={shortcut.id} className="shortcut-edit-row">
              <strong>{shortcut.title}</strong>
              <span className="field-hint">{shortcut.page}</span>
              <span className="field-hint">{bindingToDisplay(shortcut.binding)}</span>
              <button type="button" className="button button--secondary" onClick={() => handleDeleteCustomShortcut(shortcut.id)}>
                Delete
              </button>
            </div>
          ))}
          {customShortcuts.length === 0 ? <div className="field-hint">No custom page shortcuts yet.</div> : null}
        </div>
      </section>

      {showCustomForm ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="custom-shortcut-title">
          <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
            <div className="panel__header">
              <div>
                <p className="eyebrow">Custom shortcut</p>
                <h2 id="custom-shortcut-title" className="nav-panel__title">Add shortcut</h2>
              </div>
              <button type="button" className="button button--secondary" onClick={() => setShowCustomForm(false)}>
                Close
              </button>
            </div>

            <div className="stack">
              <div className="field">
                <label htmlFor="custom-shortcut-title-input">Title</label>
                <input id="custom-shortcut-title-input" className="input" value={customTitle} onChange={(event) => setCustomTitle(event.target.value)} placeholder="Open company" />
              </div>

              <div className="field">
                <label htmlFor="custom-shortcut-page">Page</label>
                <select id="custom-shortcut-page" className="select" value={customPage} onChange={(event) => setCustomPage(event.target.value)}>
                  {pageOptions.map((page) => (
                    <option key={page.value} value={page.value}>
                      {page.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label htmlFor="custom-shortcut-page-url">Or paste page URL</label>
                <input id="custom-shortcut-page-url" className="input" value={customPage} onChange={(event) => setCustomPage(event.target.value)} placeholder="/company" />
              </div>

              <div className="field">
                <label>Shortcut</label>
                <button
                  type="button"
                  className="input shortcut-capture-button"
                  onClick={() => setCustomRecording(true)}
                  onKeyDown={(event) => {
                    if (customRecording) {
                      captureCustomBinding(event);
                    }
                  }}
                >
                  {customRecording ? 'Press a shortcut...' : bindingToDisplay(customBinding)}
                </button>
              </div>

              <div className="button-row">
                <button type="button" className="button button--secondary" onClick={() => setShowCustomForm(false)}>
                  Cancel
                </button>
                <button type="button" className="button button--primary" onClick={handleSaveCustomShortcut} disabled={!customTitle.trim()}>
                  Save
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
