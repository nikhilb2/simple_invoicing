export type VoucherType = 'sales' | 'purchase';
export type ProductSortBy = 'quantity' | 'revenue' | 'name' | 'stock';
export type SortDir = 'asc' | 'desc';

/** The window the server actually reported on, after resolving FY/date fallbacks. */
export type ReportPeriod = {
  from_date: string;
  to_date: string;
  financial_year_id: number | null;
  fy_label: string | null;
};

export type MonthlySalesRow = {
  month: string;
  label: string;
  invoice_count: number;
  total_sales: number;
  taxable_value: number;
  gst_collected: number;
  discount_given: number;
  average_invoice_value: number;
};

export type MonthlySalesTotals = Omit<MonthlySalesRow, 'month' | 'label'>;

export type MonthlySalesReport = {
  currency_code: string;
  voucher_type: VoucherType;
  period: ReportPeriod;
  rows: MonthlySalesRow[];
  totals: MonthlySalesTotals;
};

export type ProductSalesRow = {
  product_id: number;
  name: string;
  sku: string | null;
  quantity_sold: number;
  sales_amount: number;
  average_selling_price: number;
  total_revenue: number;
  total_gst: number;
  invoice_count: number;
  /** null when the product isn't stock-tracked — render as "—", not 0. */
  current_stock: number | null;
};

export type ProductSalesTotals = {
  product_count: number;
  quantity_sold: number;
  sales_amount: number;
  total_revenue: number;
  total_gst: number;
  invoice_count: number;
};

export type ProductSalesReport = {
  currency_code: string;
  voucher_type: VoucherType;
  period: ReportPeriod;
  sort_by: ProductSortBy;
  sort_dir: SortDir;
  rows: ProductSalesRow[];
  totals: ProductSalesTotals;
};

/** Filters shared by both reports; product-only fields are optional. */
export type AnalyticsFilters = {
  voucherType: VoucherType;
  financialYearId?: number;
  fromDate?: string;
  toDate?: string;
  ledgerId?: number;
  productId?: number;
};
