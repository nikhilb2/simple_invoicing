export type Gstr3bSource = 'from_books' | 'not_tracked';

export type Gstr3bRowComponent = {
  label: string;
  taxable_value: number | null;
  igst: number;
  cgst: number;
  sgst: number;
};

/** A `not_tracked` row has null figures: zero would read as "you have none". */
export type Gstr3bRow = {
  key: string;
  table: string;
  label: string;
  source: Gstr3bSource;
  note: string | null;
  taxable_value: number | null;
  igst: number | null;
  cgst: number | null;
  sgst: number | null;
  components: Gstr3bRowComponent[];
};

export type Gstr3bSection = {
  key: string;
  title: string;
  note: string | null;
  rows: Gstr3bRow[];
};

export type Gstr3bSetOffLine = {
  head: 'igst' | 'cgst' | 'sgst';
  output_tax: number;
  input_credit: number;
  credit_used: number;
  payable: number;
  credit_carried_forward: number;
};

export type Gstr3bSetOff = {
  source: 'from_books';
  note: string;
  lines: Gstr3bSetOffLine[];
  total_payable: number;
  total_credit_carried_forward: number;
  rows: Gstr3bRow[];
};

export type Gstr3bWarningDocument = {
  kind: 'invoice' | 'credit_note';
  id: number;
  number: string;
  detail: string | null;
};

export type Gstr3bWarning = {
  code: string;
  severity: 'warning' | 'info';
  title: string;
  message: string;
  documents: Gstr3bWarningDocument[];
};

export type Gstr3bWorksheet = {
  title: string;
  headline: string;
  disclaimer: string;
  from_date: string;
  to_date: string;
  period_type: 'month' | 'quarter';
  period_label: string;
  warnings: Gstr3bWarning[];
  known_limits: string[];
  sections: Gstr3bSection[];
  setoff: Gstr3bSetOff;
  table_5_1_note: string;
};

export type Gstr3bExportFormat = 'csv' | 'pdf';
