export type InvoiceFormItem = {
  id: number;
  productId: string;
  quantity: string;
  unit_price: string;
  description: string;
};

export type ProductFormState = {
  name: string;
  sku: string;
  hsn_sac: string;
  price: string;
  gst_rate: string;
  maintain_inventory: boolean;
};

export type StockFormState = {
  productId: string;
  adjustment: string;
};

export function createItem(id: number, productId = '', unitPrice = ''): InvoiceFormItem {
  return {
    id,
    productId,
    quantity: '1',
    unit_price: unitPrice,
    description: '',
  };
}
