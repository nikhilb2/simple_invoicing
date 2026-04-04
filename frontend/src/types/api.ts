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
};

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
  ledger: Ledger | null;
  taxable_amount: number;
  total_tax_amount: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  total_amount: number;
  invoice_date: string;
  due_date: string | null;
  created_at: string;
  items: InvoiceItem[];
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

export type InvoiceCreate = {
  voucher_type: 'sales' | 'purchase';
  ledger_id: number;
  invoice_date?: string;
  due_date?: string;
  items: InvoiceItemInput[];
};

export type LedgerStatementEntry = {
  entry_id: number;
  entry_type: 'invoice' | 'payment';
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
};

export type DayBookEntry = {
  entry_id: number;
  entry_type: 'invoice' | 'payment';
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
};

export type Payment = {
  id: number;
  ledger_id: number;
  voucher_type: 'receipt' | 'payment';
  amount: number;
  date: string;
  mode: string | null;
  reference: string | null;
  notes: string | null;
  created_by: number;
  created_at: string;
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