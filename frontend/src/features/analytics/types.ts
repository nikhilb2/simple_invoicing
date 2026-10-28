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

export type ProfitLossProductRow = {
  product_id: number;
  name: string;
  sku: string | null;
  quantity_sold: number;
  sales_amount: number; // revenue, ex-GST
  average_selling_price: number;
  purchase_price: number; // current unit cost
  cogs: number;
  gross_profit: number;
  margin_pct: number;
};

export type ProfitLossMonthlyRow = {
  month: string;
  label: string;
  quantity: number;
  revenue: number;
  cogs: number;
  gross_profit: number;
  margin_pct: number;
};

export type ProfitLossCustomerRow = {
  ledger_id: number | null;
  name: string;
  revenue: number;
  cogs: number;
  gross_profit: number;
  margin_pct: number;
  invoice_count: number;
};

export type ProfitLossTotals = {
  product_count: number;
  quantity_sold: number;
  revenue: number;
  cogs: number;
  gross_profit: number;
  margin_pct: number;
};

export type ProfitLossReport = {
  currency_code: string;
  voucher_type: VoucherType;
  period: ReportPeriod;
  product_rows: ProfitLossProductRow[];
  monthly_rows: ProfitLossMonthlyRow[];
  customer_rows: ProfitLossCustomerRow[];
  totals: ProfitLossTotals;
};

export type PerformanceSortBy =
  | 'name'
  | 'units_sold'
  | 'units_returned'
  | 'net_units_sold'
  | 'units_bought'
  | 'net_units_bought'
  | 'average_selling_price'
  | 'average_buying_price'
  | 'revenue'
  | 'purchase_spend'
  | 'cogs'
  | 'gross_profit'
  | 'margin_pct'
  | 'profit_per_unit'
  | 'current_stock';

/** Where a row's unit cost came from. null means no cost is known at all. */
export type CostBasis = 'purchases' | 'current_price';

/**
 * One product's sales, purchases, returns and margin. All money is ex-GST.
 * Cost-derived fields are null when the product has no purchases in the period
 * and no purchase price — render "—", never 0.
 */
export type ProductPerformanceRow = {
  product_id: number;
  name: string;
  sku: string | null;
  units_sold: number;
  units_returned: number;
  net_units_sold: number;
  units_bought: number;
  units_purchase_returned: number;
  net_units_bought: number;
  average_selling_price: number | null;
  average_buying_price: number | null;
  cost_basis: CostBasis | null;
  sales_value: number;
  return_value: number;
  revenue: number;
  purchase_value: number;
  purchase_return_value: number;
  purchase_spend: number;
  cogs: number | null;
  gross_profit: number | null;
  margin_pct: number | null;
  profit_per_unit: number | null;
  current_stock: number | null;
};

export type ProductPerformanceTotals = {
  product_count: number;
  units_sold: number;
  units_returned: number;
  net_units_sold: number;
  units_bought: number;
  units_purchase_returned: number;
  net_units_bought: number;
  sales_value: number;
  return_value: number;
  revenue: number;
  purchase_value: number;
  purchase_return_value: number;
  purchase_spend: number;
  /** Revenue of the rows that have a cost; profit and margin cover only these. */
  costed_revenue: number;
  cogs: number;
  gross_profit: number;
  margin_pct: number | null;
  uncosted_product_count: number;
  current_price_product_count: number;
};

export type ProductPerformanceReport = {
  currency_code: string;
  period: ReportPeriod;
  sort_by: PerformanceSortBy;
  sort_dir: SortDir;
  rows: ProductPerformanceRow[];
  totals: ProductPerformanceTotals;
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
