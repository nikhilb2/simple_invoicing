export type RowEditValues = {
  name: string;
  sku: string;
  selling_price: string;
  purchase_price: string;
  reorder_level: string;
  gst_rate: string;
};

export type ParsedRowEdit = {
  selling_price: number;
  purchase_price: number;
  reorder_level: number;
  gst_rate: number;
};

export type RowEditParseResult =
  | { ok: true; value: ParsedRowEdit }
  | { ok: false; error: string };

export function parseRowEdit(values: RowEditValues): RowEditParseResult {
  if (!values.name.trim()) {
    return { ok: false, error: 'Product name cannot be empty.' };
  }
  if (!values.sku.trim()) {
    return { ok: false, error: 'SKU cannot be empty.' };
  }
  const selling = Number(values.selling_price);
  if (values.selling_price.trim() === '' || Number.isNaN(selling) || selling < 0) {
    return { ok: false, error: 'Selling price must be a number of 0 or more.' };
  }
  const purchase = Number(values.purchase_price);
  if (values.purchase_price.trim() === '' || Number.isNaN(purchase) || purchase < 0) {
    return { ok: false, error: 'Purchase price must be a number of 0 or more.' };
  }
  const reorder = Number(values.reorder_level);
  if (values.reorder_level.trim() === '' || Number.isNaN(reorder) || reorder < 0) {
    return { ok: false, error: 'Reorder level must be a number of 0 or more.' };
  }
  const gst = Number(values.gst_rate);
  if (values.gst_rate.trim() === '' || Number.isNaN(gst) || gst < 0 || gst > 100) {
    return { ok: false, error: 'GST rate must be between 0 and 100.' };
  }
  return {
    ok: true,
    value: {
      selling_price: selling,
      purchase_price: purchase,
      reorder_level: reorder,
      gst_rate: gst,
    },
  };
}
