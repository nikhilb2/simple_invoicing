import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import ProductFormModal from './ProductFormModal';
import type { CatalogueRow } from './types';

function row(overrides: Partial<CatalogueRow> = {}): CatalogueRow {
  return {
    id: 41,
    sku: 'TEE-RED-M',
    name: 'Cotton tee, red, M',
    description: 'Combed cotton',
    hsn_sac: '6109',
    purchase_price: 180,
    selling_price: 349,
    current_stock: 25,
    reorder_level: 5,
    status: 'active',
    unit: 'Pieces',
    gst_rate: 5,
    track_serials: false,
    maintain_inventory: true,
    allow_decimal: false,
    is_producable: false,
    production_cost: null,
    date_added: '2026-04-01',
    last_sold_at: null,
    ...overrides,
  };
}

const noop = () => {};

/* Vitest runs in node with no DOM here, so the form is read back from the
   server-rendered markup. */
function render(props: { row?: CatalogueRow | null; template?: CatalogueRow | null }) {
  const html = renderToStaticMarkup(
    <ProductFormModal
      row={props.row ?? null}
      template={props.template}
      onCancel={noop}
      onSaved={noop}
      onNeedsSerialBackfill={noop}
      onConfigureBom={noop}
    />,
  );
  const value = (id: string) => html.match(new RegExp(`<input id="${id}"[^>]*value="([^"]*)"`))?.[1];
  // In render order: maintain stock, fractional quantities, serials, manufactured in-house.
  const checkboxes = [...html.matchAll(/<input type="checkbox"[^>]*>/g)].map((m) => m[0].includes('checked=""'));
  return { html, value, checkboxes };
}

describe('ProductFormModal duplicate', () => {
  test('opens as a new product prefilled with the attributes similar products share', () => {
    const { html, value, checkboxes } = render({ template: row() });

    expect(html).toContain('New product from Cotton tee, red, M');
    expect(html).toContain('Create product');
    expect(value('product-name')).toBe('Cotton tee, red, M');
    expect(value('product-price')).toBe('349');
    expect(value('product-purchase-price')).toBe('180');
    expect(value('product-gst')).toBe('5');
    expect(value('product-hsn')).toBe('6109');
    expect(value('product-reorder')).toBe('5');
    expect(html).toMatch(/<textarea id="product-description"[^>]*>Combed cotton<\/textarea>/);
    expect(checkboxes).toEqual([true, false, false, false]);
  });

  test('leaves the SKU blank and starts with no opening stock', () => {
    const { html, value } = render({ template: row({ current_stock: 25 }) });

    expect(value('product-sku')).toBe('');
    expect(html).toContain('Opening stock');
    expect(value('product-initial-qty')).toBe('0');
  });

  test('copies the unit and the behaviour flags', () => {
    const { value, checkboxes } = render({
      template: row({ unit: 'Box of 12', maintain_inventory: false, allow_decimal: true }),
    });

    expect(value('product-custom-unit')).toBe('Box of 12');
    expect(checkboxes).toEqual([false, true, false, false]);
  });

  test('keeps serial tracking on, but carries none of the source serials', () => {
    const { html, checkboxes } = render({ template: row({ track_serials: true, current_stock: 3 }) });

    expect(checkboxes[2]).toBe(true);
    expect(html).toContain('Serials (0)');
    expect(html).not.toContain('class="serial-chip"');
  });

  test('keeps a producable product producable, with its production cost', () => {
    const { value, checkboxes } = render({ template: row({ is_producable: true, production_cost: 120.5 }) });

    expect(checkboxes[3]).toBe(true);
    expect(value('product-production-cost')).toBe('120.5');
  });

  test('editing and plain create are unchanged', () => {
    const edit = render({ row: row() });
    expect(edit.html).toContain('Editing Cotton tee, red, M');
    expect(edit.value('product-sku')).toBe('TEE-RED-M');

    const create = render({});
    expect(create.html).toContain('Add a product');
    expect(create.value('product-name')).toBe('');
  });
});
