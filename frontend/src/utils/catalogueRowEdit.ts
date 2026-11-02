import type { CatalogueRow, RowEdit } from '../pages/catalogue/types';

type ParsedRowEdit = Pick<CatalogueRow, keyof RowEdit>;

export function parseRowEdit(values: RowEdit):
  | { ok: true; value: ParsedRowEdit }
  | { ok: false; error: string } {
  if (!values.name.trim()) return { ok: false, error: 'Product name cannot be empty.' };
  if (!values.sku.trim()) return { ok: false, error: 'SKU cannot be empty.' };

  const fields = [
    ['selling_price', 'Selling price'],
    ['purchase_price', 'Purchase price'],
    ['reorder_level', 'Reorder level'],
    ['gst_rate', 'GST rate'],
  ] as const;
  for (const [field, label] of fields) {
    if (!values[field].trim()) return { ok: false, error: `${label} is required.` };
    const number = Number(values[field]);
    if (!Number.isFinite(number) || number < 0 || (field === 'gst_rate' && number > 100)) {
      return {
        ok: false,
        error: field === 'gst_rate'
          ? 'GST rate must be between 0 and 100.'
          : `${label} must be a number of 0 or more.`,
      };
    }
  }

  return {
    ok: true,
    value: {
      name: values.name.trim(),
      sku: values.sku.trim(),
      selling_price: Number(values.selling_price),
      purchase_price: Number(values.purchase_price),
      reorder_level: Number(values.reorder_level),
      gst_rate: Number(values.gst_rate),
    },
  };
}
