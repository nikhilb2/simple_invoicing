export const ACTION_KEYS = [
  'create_invoice', 'save_invoice', 'open_search', 'open_reports',
  'new_customer', 'go_invoices', 'go_ledgers', 'go_products',
  'go_day_book', 'go_tax_ledger', 'focus_scan',
  'go_invoice_dues', 'go_credit_notes', 'go_gstr1', 'go_dashboard',
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
  go_day_book:    'Alt+D',
  go_tax_ledger:  'Alt+T',
  focus_scan:     'Alt+S',
  go_invoice_dues: 'Alt+U',
  go_credit_notes: 'Alt+N',
  go_gstr1:        'Alt+G',
  go_dashboard:    'Alt+O',
};

export const ACTION_LABELS: Record<ActionKey, string> = {
  create_invoice: 'New Invoice',
  save_invoice:   'Save Invoice',
  open_search:    'Search',
  open_reports:   'Open Reports',
  new_customer:   'New Customer',
  go_invoices:    'Go to Invoices',
  go_ledgers:     'Go to Ledgers',
  go_products:    'Go to Products & Stock',
  go_day_book:    'Go to Day Book',
  go_tax_ledger:  'Go to Tax Ledger',
  focus_scan:     'Focus scan box',
  go_invoice_dues: 'Go to Invoice Dues',
  go_credit_notes: 'Go to Credit / Debit Notes',
  go_gstr1:        'Go to GSTR-1 Filing',
  go_dashboard:    'Go to Dashboard',
};
