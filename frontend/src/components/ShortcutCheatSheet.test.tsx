import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';
import { ACTION_KEYS, ACTION_LABELS, DEFAULT_SHORTCUTS, type ActionKey } from '../utils/shortcutDefaults';
import ShortcutCheatSheet from './ShortcutCheatSheet';

// The user has moved two actions off their defaults.
const custom: Partial<Record<ActionKey, string>> = {
  go_invoices: 'Ctrl+Shift+I',
  save_invoice: 'Alt+Enter',
};

vi.mock('../context/ShortcutsContext', () => ({
  useShortcuts: () => ({
    shortcutFor: (key: ActionKey) => custom[key] ?? DEFAULT_SHORTCUTS[key],
  }),
}));

function render() {
  return renderToStaticMarkup(
    <MemoryRouter>
      <ShortcutCheatSheet onClose={() => {}} />
    </MemoryRouter>,
  );
}

function keyFor(html: string, label: string) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&').replace(/&/g, '&amp;');
  return html.match(new RegExp(`<dt>${escaped}</dt><dd><kbd>([^<]*)</kbd></dd>`))?.[1];
}

describe('ShortcutCheatSheet', () => {
  test('is a modal dialog named by its heading', () => {
    const html = render();

    expect(html).toMatch(/role="dialog"[^>]*aria-modal="true"[^>]*aria-labelledby="shortcut-cheat-sheet-title"/);
    expect(html).toContain('<h2 id="shortcut-cheat-sheet-title" class="nav-panel__title">Keyboard shortcuts</h2>');
    expect(html).toContain('aria-label="Close keyboard shortcuts"');
  });

  test('lists every action once', () => {
    const html = render();

    expect(html.match(/<dt>/g)).toHaveLength(ACTION_KEYS.length);
    for (const key of ACTION_KEYS) {
      expect(keyFor(html, ACTION_LABELS[key])).toBeDefined();
    }
  });

  test("shows the user's own keys where they changed them, and defaults elsewhere", () => {
    const html = render();

    expect(keyFor(html, 'Go to Invoices')).toBe('Ctrl+Shift+I');
    expect(keyFor(html, 'Save Invoice')).toBe('Alt+Enter');
    expect(keyFor(html, 'New Invoice')).toBe(DEFAULT_SHORTCUTS.create_invoice);
    expect(html).not.toContain(`<kbd>${DEFAULT_SHORTCUTS.go_invoices}</kbd>`);
  });

  test('links to the Keyboard Shortcuts page for changing them', () => {
    expect(render()).toContain('href="/settings/shortcuts"');
  });
});
