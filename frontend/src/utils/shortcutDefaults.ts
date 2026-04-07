export const ACTION_KEYS = [
  'create_invoice', 'save_invoice', 'open_search', 'open_reports',
  'new_customer', 'go_invoices', 'go_ledgers', 'go_products',
  'go_inventory', 'go_day_book',
] as const;

export type ActionKey = typeof ACTION_KEYS[number];

export const DEFAULT_SHORTCUTS: Record<ActionKey, string> = {
  create_invoice: 'Ctrl+N',
  save_invoice:   'Ctrl+S',
  open_search:    'Ctrl+F',
  open_reports:   'Ctrl+R',
  new_customer:   'Ctrl+Shift+C',
  go_invoices:    'Alt+I',
  go_ledgers:     'Alt+L',
  go_products:    'Alt+P',
  go_inventory:   'Alt+V',
  go_day_book:    'Alt+D',
};

export const ACTION_LABELS: Record<ActionKey, string> = {
  create_invoice: 'New Invoice',
  save_invoice:   'Save Invoice',
  open_search:    'Search',
  open_reports:   'Open Reports',
  new_customer:   'New Customer',
  go_invoices:    'Go to Invoices',
  go_ledgers:     'Go to Ledgers',
  go_products:    'Go to Products',
  go_inventory:   'Go to Inventory',
  go_day_book:    'Go to Day Book',
};
