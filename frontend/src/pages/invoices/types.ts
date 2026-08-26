export type DiscountType = 'percentage' | 'net';

export type InvoiceFormItem = {
  id: number;
  productId: string;
  quantity: string;
  unit_price: string;
  description: string;
  discount_type: DiscountType | '';
  discount_value: string;
  /** Serial / IMEI numbers on this line. Empty for products that are fungible. */
  serials: string[];
  /**
   * The product on this line was seeded by the composer, not chosen by anyone.
   * A scan that needs a new line takes such a line over instead of leaving a
   * stray default line on the invoice; any edit to the line clears the flag, so
   * a line the user actually picked is never overwritten.
   */
  autoFilled: boolean;
};

export type ProductFormState = {
  name: string;
  sku: string;
  hsn_sac: string;
  price: string;
  gst_rate: string;
  unit: string;
  allow_decimal: boolean;
  maintain_inventory: boolean;
  track_serials: boolean;
};

export type StockFormState = {
  productId: string;
  adjustment: string;
  /* One per unit when the product is serial-tracked; the adjustment is blocked
     until the count matches, so stock and serials can never drift apart. */
  serials: string[];
  note: string;
};

export function createItem(id: number, productId = '', unitPrice = ''): InvoiceFormItem {
  return {
    id,
    productId,
    quantity: '1',
    unit_price: unitPrice,
    description: '',
    discount_type: '',
    discount_value: '',
    serials: [],
    autoFilled: true,
  };
}
