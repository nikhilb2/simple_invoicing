import { useEffect, useState } from 'react';
import {
  bindingToDisplay,
  defaultShortcutPreferences,
  loadShortcutPreferences,
  saveShortcutPreferences,
  type ShortcutAction,
  type ShortcutBinding,
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

export default function KeyboardShortcutsPage() {
  const [preferences, setPreferences] = useState<ShortcutPreferences>(defaultShortcutPreferences);

  useEffect(() => {
    setPreferences(loadShortcutPreferences());
  }, []);

  function updateBinding(action: ShortcutAction, updates: Partial<ShortcutBinding>) {
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
                <label className="shortcut-edit-control">
                  <span>Ctrl/Cmd</span>
                  <input type="checkbox" checked={binding.ctrlOrCmd} onChange={(event) => updateBinding(action, { ctrlOrCmd: event.target.checked })} />
                </label>
                <label className="shortcut-edit-control">
                  <span>Shift</span>
                  <input type="checkbox" checked={binding.shift} onChange={(event) => updateBinding(action, { shift: event.target.checked })} />
                </label>
                <label className="shortcut-edit-control">
                  <span>Alt</span>
                  <input type="checkbox" checked={binding.alt} onChange={(event) => updateBinding(action, { alt: event.target.checked })} />
                </label>
                <label className="shortcut-edit-control shortcut-edit-control--key">
                  <span>Key</span>
                  <input
                    className="input"
                    value={binding.key}
                    onChange={(event) => updateBinding(action, { key: event.target.value.toUpperCase() })}
                    placeholder="A"
                    maxLength={12}
                  />
                </label>
                <span className="field-hint">{bindingToDisplay(binding)}</span>
              </div>
            );
          })}
        </div>

        <div className="field-hint">
          Changes are stored locally in this browser. The composer will use the saved shortcuts after you refresh or revisit the page.
        </div>
      </section>
    </div>
  );
}
