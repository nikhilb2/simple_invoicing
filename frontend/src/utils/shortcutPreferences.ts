export type ShortcutAction = 'submit_invoice' | 'add_line_item' | 'add_ledger' | 'add_product' | 'update_stock' | 'toggle_help';

export type ShortcutBinding = {
  ctrlOrCmd: boolean;
  shift: boolean;
  alt: boolean;
  key: string;
};

export type ShortcutPreferences = Record<ShortcutAction, ShortcutBinding>;

export const shortcutActionLabels: Record<ShortcutAction, string> = {
  submit_invoice: 'Submit invoice',
  add_line_item: 'Add line item',
  add_ledger: 'Add ledger',
  add_product: 'Add product',
  update_stock: 'Update stock',
  toggle_help: 'Toggle help',
};

export const defaultShortcutPreferences: ShortcutPreferences = {
  submit_invoice: { ctrlOrCmd: true, shift: false, alt: false, key: 'Enter' },
  add_line_item: { ctrlOrCmd: false, shift: true, alt: false, key: 'A' },
  add_ledger: { ctrlOrCmd: false, shift: true, alt: false, key: 'L' },
  add_product: { ctrlOrCmd: false, shift: true, alt: false, key: 'P' },
  update_stock: { ctrlOrCmd: false, shift: true, alt: false, key: 'S' },
  toggle_help: { ctrlOrCmd: true, shift: false, alt: false, key: '/' },
};

const STORAGE_KEY = 'simple-invoicing.shortcut-preferences';

export function bindingToDisplay(binding: ShortcutBinding) {
  const parts: string[] = [];
  if (binding.ctrlOrCmd) parts.push('Ctrl/Cmd');
  if (binding.shift) parts.push('Shift');
  if (binding.alt) parts.push('Alt');
  parts.push(binding.key.toUpperCase());
  return parts.join(' + ');
}

export function loadShortcutPreferences(): ShortcutPreferences {
  if (typeof window === 'undefined') {
    return defaultShortcutPreferences;
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultShortcutPreferences;

    const parsed = JSON.parse(raw) as Partial<ShortcutPreferences>;
    return {
      ...defaultShortcutPreferences,
      ...parsed,
    };
  } catch {
    return defaultShortcutPreferences;
  }
}

export function saveShortcutPreferences(preferences: ShortcutPreferences) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  window.dispatchEvent(new CustomEvent('shortcut-preferences-updated'));
}
