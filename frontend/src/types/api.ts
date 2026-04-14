export type AuthToken = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

export type Product = {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  hsn_sac: string | null;
  price: number;
  gst_rate: number;
};

export type ProductCreate = {
  sku: string;
  name: string;
  description: string;
  hsn_sac: string;
  price: number;
  gst_rate: number;
};

export type InventoryRow = {
  product_id: number;
  product_name: string;
  quantity: number;
};

export type InventoryAdjust = {
  product_id: number;
  quantity: number;
};

export type Ledger = {
  id: number;
  name: string;
  address: string;
  gst: string;
  phone_number: string;
  email: string | null;
  website: string | null;
  bank_name: string | null;
  branch_name: string | null;
  account_name: string | null;
  account_number: string | null;
  ifsc_code: string | null;
};

export type LedgerCreate = {
  name: string;
  address: string;
  gst: string;
  phone_number: string;
  email: string;
  website: string;
  bank_name: string;
  branch_name: string;
  account_name: string;
  account_number: string;
  ifsc_code: string;
};

export type PaginatedLedgers = {
  items: Ledger[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type PaginatedProducts = {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type PaginatedInvoices = {
  items: Invoice[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  summary?: {
    total_listed: number;
    credit_total: number;
    debit_total: number;
    cancelled_total: number;
    active_total: number;
    others_total: number;
    visible_page_total: number;
    visible_page_count: number;
    filtered_count: number;
    include_cancelled: boolean;
    financial_year_id: number | null;
  };
};

export type CreditNoteType = 'return' | 'discount' | 'adjustment';
export type CreditNoteStatus = 'active' | 'cancelled';

export type CompanyProfile = {
  id: number;
  name: string;
  address: string;
  gst: string;
  phone_number: string;
  currency_code: string | null;
  email: string | null;
  website: string | null;
  bank_name: string | null;
  branch_name: string | null;
  account_name: string | null;
  account_number: string | null;
  ifsc_code: string | null;
};

export type CompanyProfileUpdate = {
  name: string;
  address: string;
  gst: string;
  phone_number: string;
  currency_code: string;
  email: string;
  website: string;
  bank_name: string;
  branch_name: string;
  account_name: string;
  account_number: string;
  ifsc_code: string;
};

export type Invoice = {
  id: number;
  invoice_number: string | null;
  ledger_id: number | null;
  ledger_name: string | null;
  ledger_address: string | null;
  ledger_gst: string | null;
  ledger_phone: string | null;
  company_name: string | null;
  company_address: string | null;
  company_gst: string | null;
  company_phone: string | null;
  company_email: string | null;
  company_website: string | null;
  company_currency_code: string | null;
  company_bank_name: string | null;
  company_branch_name: string | null;
  company_account_name: string | null;
  company_account_number: string | null;
  company_ifsc_code: string | null;
  voucher_type: 'sales' | 'purchase';
  status: 'active' | 'cancelled';
  tax_inclusive: boolean;
  supplier_invoice_number?: string | null;
  ledger: Ledger | null;
  taxable_amount: number;
  total_tax_amount: number;
  credit_status: 'not_credited' | 'partially_credited' | 'fully_credited';
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  total_amount: number;
  invoice_date: string;
  due_date: string | null;
  created_at: string;
  items: InvoiceItem[];
  warnings?: string[];
};

export type InvoiceItem = {
  id: number;
  product_id: number;
  hsn_sac: string | null;
  quantity: number;
  unit_price: number;
  gst_rate: number;
  taxable_amount: number;
  tax_amount: number;
  line_total: number;
};

export type InvoiceItemInput = {
  product_id: number;
  quantity: number;
  unit_price?: number;
};

export type CreditNoteItem = {
  id: number;
  invoice_id: number | null;
  invoice_item_id: number | null;
  product_id: number | null;
  quantity: number;
  unit_price: number;
  gst_rate: number;
  taxable_amount: number;
  tax_amount: number;
  line_total: number;
};

export type CreditNote = {
  id: number;
  credit_note_number: string;
  ledger_id: number;
  financial_year_id: number | null;
  credit_note_type: CreditNoteType;
  reason: string | null;
  status: CreditNoteStatus;
  taxable_amount: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  total_amount: number;
  created_at: string;
  cancelled_at: string | null;
  invoice_ids: number[];
  items: CreditNoteItem[];
};

export type CreditNoteItemCreate = {
  invoice_id: number;
  invoice_item_id: number;
  quantity?: number;
  discount_amount_inclusive?: number;
};

export type CreditNoteCreate = {
  ledger_id: number;
  invoice_ids: number[];
  credit_note_type: CreditNoteType;
  reason?: string | null;
  items: CreditNoteItemCreate[];
};

export type PaginatedCreditNotes = {
  items: CreditNote[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type InvoiceCreate = {
  voucher_type: 'sales' | 'purchase';
  ledger_id: number;
  invoice_date?: string;
  due_date?: string;
  supplier_invoice_number?: string | null;
  tax_inclusive?: boolean;
  items: InvoiceItemInput[];
};

export type LedgerStatementEntry = {
  entry_id: number;
  entry_type: 'invoice' | 'payment' | 'credit_note';
  date: string;
  voucher_type: string;
  particulars: string;
  debit: number;
  credit: number;
};

export type LedgerStatement = {
  ledger: Ledger;
  from_date: string;
  to_date: string;
  opening_balance: number;
  period_debit: number;
  period_credit: number;
  closing_balance: number;
  entries: LedgerStatementEntry[];
  fy_label: string | null;
  financial_year_id: number | null;
};

export type DayBookEntry = {
  entry_id: number;
  entry_type: 'invoice' | 'payment' | 'credit_note';
  date: string;
  voucher_type: string;
  ledger_name: string;
  particulars: string;
  debit: number;
  credit: number;
};

export type DayBook = {
  from_date: string;
  to_date: string;
  total_debit: number;
  total_credit: number;
  entries: DayBookEntry[];
  fy_label: string | null;
  financial_year_id: number | null;
};

export type Payment = {
  id: number;
  ledger_id: number;
  voucher_type: 'receipt' | 'payment';
  amount: number;
  date: string;
  payment_number?: string | null;
  mode: string | null;
  reference: string | null;
  notes: string | null;
  status: string;
  created_by: number;
  created_at: string;
  warnings?: string[];
};

export type PaymentUpdate = {
  voucher_type: 'receipt' | 'payment';
  amount: number;
  date?: string;
  mode?: string;
  reference?: string;
  notes?: string;
};

export type PaymentCreate = {
  ledger_id: number;
  voucher_type: 'receipt' | 'payment';
  amount: number;
  date?: string;
  mode?: string;
  reference?: string;
  notes?: string;
};

export type UserProfile = {
  id: number;
  email: string;
  full_name: string;
  role: 'admin' | 'manager' | 'staff';
};

export type SmtpConfig = {
  id: number;
  name: string;
  host: string;
  port: number;
  username: string;
  from_email: string;
  from_name: string;
  use_starttls: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type SmtpConfigCreate = {
  name: string;
  host: string;
  port: number;
  username: string;
  password: string;
  from_email: string;
  from_name: string;
  use_starttls: boolean;
};

export type SmtpConfigUpdate = {
  name?: string;
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  from_email?: string;
  from_name?: string;
  use_starttls?: boolean;
};

export type UserShortcut = {
  action_key: string;
  shortcut_key: string;
};

export type UserShortcutsResponse = {
  shortcuts: UserShortcut[];
};

export type InvoiceSeries = {
  id: number;
  voucher_type: string;
  prefix: string;
  suffix: string;
  include_year: boolean;
  year_format: 'YYYY' | 'MM-YYYY' | 'FY';
  separator: string;
  next_sequence: number;
  pad_digits: 2 | 3 | 4;
  created_at: string | null;
};

export type InvoiceSeriesUpdate = {
  prefix: string;
  suffix: string;
  include_year: boolean;
  year_format: 'YYYY' | 'MM-YYYY' | 'FY';
  separator: string;
  pad_digits: 2 | 3 | 4;
};

export type BackupSummary = {
  file_name: string;
  size_bytes: number;
  created_at: string;
  migration_head: string | null;
};

export type BackupCreateResponse = {
  file_name: string;
  size_bytes: number;
  created_at: string;
  migration_head: string | null;
};

export type BackupPreflightResponse = {
  valid: boolean;
  compatibility: 'exact' | 'requires_migration' | 'newer_than_app' | 'diverged' | string;
  reason: string | null;
  backup_created_at: string | null;
  backup_migration_head: string | null;
  current_migration_head: string | null;
  migration_gap_count: number | null;
};

export type BackupRestoreResponse = {
  detail: string;
  compatibility: string;
  applied_migrations: number;
};