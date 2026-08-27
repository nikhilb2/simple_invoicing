import { useEffect, useRef, useState } from 'react';
import { Settings2 } from 'lucide-react';
import api, { getApiErrorMessage } from '../../api/client';
import { track } from '../../lib/analytics';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import type { Product, ProductCreate } from '../../types/api';
import SerialChips from '../invoices/components/SerialChips';
import type { CatalogueRow } from './types';

const UNIT_OPTIONS = ['Pieces', 'Kg', 'g', 'm', 'l', 'Ounce'];
const CUSTOM_UNIT_VALUE = '__custom__';

/**
 * Create and edit a product's attributes.
 *
 * The old Products page kept this form permanently expanded in a sticky column
 * beside the list, where it had its own inner scrollbar next to the page's. As a
 * modal it is summoned when needed, and the catalogue table gets the full width.
 *
 * Stock is deliberately absent except as opening stock on create: an existing
 * product's quantity only ever moves through the audited adjustment flow, so
 * this form cannot be used to overwrite it.
 */

/** All the backfill sheet needs to identify the product it is completing. */
export type BackfillTarget = { id: number; name: string; sku: string };

type ProductFormModalProps = {
  /** The row being edited, or null to create. */
  row: CatalogueRow | null;
  onCancel: () => void;
  onSaved: (message: string) => void;
  /**
   * Turning on serial tracking for a product that already holds stock owes one
   * serial per unit on the shelf, so that edit finishes in the backfill sheet.
   * The page owns that modal; this form hands it the pending payload.
   */
  onNeedsSerialBackfill: (product: BackfillTarget, payload: ProductCreate) => void;
  /** Opens the bill-of-materials editor for a saved producable product. */
  onConfigureBom: (productId: number, productName: string) => void;
};

type FormState = {
  sku: string;
  name: string;
  description: string;
  hsn_sac: string;
  price: string;
  purchase_price: string;
  gst_rate: string;
  reorder_level: string;
  unit: string;
  allow_decimal: boolean;
  maintain_inventory: boolean;
  track_serials: boolean;
  initial_quantity: string;
  /* Opening stock for a serial-tracked product is the length of this list, not
     a number anyone types. */
  serial_numbers: string[];
  is_producable: boolean;
  production_cost: string;
};

function emptyForm(): FormState {
  return {
    sku: '',
    name: '',
    description: '',
    hsn_sac: '',
    price: '',
    purchase_price: '',
    gst_rate: '0',
    reorder_level: '0',
    unit: 'Pieces',
    allow_decimal: false,
    maintain_inventory: true,
    track_serials: false,
    initial_quantity: '0',
    serial_numbers: [],
    is_producable: false,
    production_cost: '',
  };
}

function formFromRow(row: CatalogueRow): FormState {
  return {
    sku: row.sku,
    name: row.name,
    description: row.description ?? '',
    hsn_sac: row.hsn_sac ?? '',
    price: String(row.selling_price),
    purchase_price: String(row.purchase_price),
    gst_rate: String(row.gst_rate),
    reorder_level: String(row.reorder_level),
    unit: row.unit || 'Pieces',
    allow_decimal: row.allow_decimal,
    maintain_inventory: row.maintain_inventory,
    track_serials: row.track_serials,
    initial_quantity: '0',
    serial_numbers: [],
    is_producable: row.is_producable,
    production_cost: row.production_cost != null ? String(row.production_cost) : '',
  };
}

export default function ProductFormModal({
  row,
  onCancel,
  onSaved,
  onNeedsSerialBackfill,
  onConfigureBom,
}: ProductFormModalProps) {
  const isEdit = row !== null;
  const [form, setForm] = useState<FormState>(() => (row ? formFromRow(row) : emptyForm()));
  const [customUnit, setCustomUnit] = useState(() =>
    row && row.unit && !UNIT_OPTIONS.includes(row.unit) ? row.unit : '',
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const firstFieldRef = useRef<HTMLInputElement | null>(null);

  useEscapeClose(onCancel);

  // Opening a dialog should land the caret in it, not leave focus behind on the
  // button that summoned it.
  useEffect(() => {
    firstFieldRef.current?.focus();
  }, []);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  /** Serial tracking rules out fractional units and cannot run without stock. */
  function setTrackSerials(checked: boolean) {
    setForm((current) => ({
      ...current,
      track_serials: checked,
      allow_decimal: checked ? false : current.allow_decimal,
      maintain_inventory: checked ? true : current.maintain_inventory,
      serial_numbers: checked ? current.serial_numbers : [],
    }));
  }

  const unitIsCustom = !UNIT_OPTIONS.includes(form.unit) || form.unit === CUSTOM_UNIT_VALUE;
  const resolvedUnit = unitIsCustom ? customUnit.trim() : form.unit;

  function buildPayload(): ProductCreate {
    const openingQuantity = form.track_serials
      ? form.serial_numbers.length
      : Number(form.initial_quantity || 0);

    return {
      sku: form.sku.trim(),
      name: form.name.trim(),
      description: form.description.trim(),
      hsn_sac: form.hsn_sac.trim(),
      price: Number(form.price),
      gst_rate: Number(form.gst_rate),
      unit: resolvedUnit || 'Pieces',
      allow_decimal: form.allow_decimal,
      maintain_inventory: form.maintain_inventory,
      track_serials: form.track_serials,
      is_producable: form.is_producable,
      production_cost: form.production_cost !== '' ? Number(form.production_cost) : null,
      ...(isEdit
        ? {}
        : {
            initial_quantity: openingQuantity,
            ...(form.track_serials ? { serial_numbers: form.serial_numbers } : {}),
          }),
    };
  }

  /** Everything the server would reject, said inline before a round trip. */
  function validate(): string {
    if (!form.sku.trim()) return 'SKU is required.';
    if (!form.name.trim()) return 'Product name is required.';
    if (form.price === '' || Number.isNaN(Number(form.price))) return 'Enter a selling price.';
    if (Number(form.price) < 0) return 'Selling price cannot be negative.';
    if (form.purchase_price !== '' && Number(form.purchase_price) < 0) {
      return 'Purchase price cannot be negative.';
    }
    const gst = Number(form.gst_rate);
    if (Number.isNaN(gst) || gst < 0 || gst > 100) return 'GST rate must be between 0 and 100.';
    if (unitIsCustom && !customUnit.trim()) return 'Enter a unit name.';
    if (form.is_producable && form.production_cost !== '' && Number(form.production_cost) < 0) {
      return 'Production cost cannot be negative.';
    }
    if (!isEdit && !form.track_serials && Number(form.initial_quantity || 0) < 0) {
      return 'Opening stock cannot be negative.';
    }
    return '';
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    const message = validate();
    if (message) {
      setError(message);
      return;
    }

    const payload = buildPayload();

    // Switching tracking on for a product that already has stock: the units on
    // the shelf need serials before the flag can be saved, and both halves
    // travel in the backfill sheet's single PUT.
    if (isEdit && row && form.track_serials && !row.track_serials) {
      onNeedsSerialBackfill({ id: row.id, name: row.name, sku: row.sku }, payload);
      return;
    }

    try {
      setSubmitting(true);
      setError('');

      if (isEdit && row) {
        await api.put<Product>(`/products/${row.id}`, payload);
        // The attribute endpoint does not carry these two, so they follow in the
        // catalogue update that owns them.
        await api.put(`/products/${row.id}/with-inventory`, {
          purchase_price: form.purchase_price === '' ? 0 : Number(form.purchase_price),
          reorder_level: form.reorder_level === '' ? 0 : Number(form.reorder_level),
        });
        onSaved(`${payload.name} updated.`);
      } else {
        const created = await api.post<Product>('/products/', payload);
        if (form.purchase_price !== '' || form.reorder_level !== '0') {
          await api.put(`/products/${created.data.id}/with-inventory`, {
            purchase_price: form.purchase_price === '' ? 0 : Number(form.purchase_price),
            reorder_level: form.reorder_level === '' ? 0 : Number(form.reorder_level),
          });
        }
        track('product_created', {
          gst_rate: payload.gst_rate,
          maintain_inventory: payload.maintain_inventory,
          track_serials: payload.track_serials,
          is_producable: payload.is_producable,
          has_opening_stock: (payload.initial_quantity ?? 0) > 0,
          source: 'catalogue_page',
        });
        onSaved(`${payload.name} created.`);
      }
    } catch (err) {
      setError(
        getApiErrorMessage(err, isEdit ? 'Unable to update product' : 'Unable to create product'),
      );
    } finally {
      setSubmitting(false);
    }
  }

  const titleId = 'product-form-title';
  const errorId = 'product-form-error';

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-panel modal-panel--product-form"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="panel__header">
          <div>
            <p className="eyebrow">{isEdit ? 'Edit' : 'New'}</p>
            <h2 className="nav-panel__title" id={titleId}>
              {isEdit ? `Editing ${row?.name}` : 'Add a product'}
            </h2>
          </div>
        </div>

        <form className="stack" onSubmit={handleSubmit}>
          <div className="field-grid">
            <label className="field" htmlFor="product-sku">
              <span>SKU</span>
              <input
                id="product-sku"
                ref={firstFieldRef}
                className="input"
                value={form.sku}
                onChange={(e) => update('sku', e.target.value)}
                placeholder="WID-001"
                required
              />
            </label>

            <label className="field" htmlFor="product-name">
              <span>Product name</span>
              <input
                id="product-name"
                className="input"
                value={form.name}
                onChange={(e) => update('name', e.target.value)}
                placeholder="Widget A"
                required
              />
            </label>

            <label className="field" htmlFor="product-price">
              <span>Selling price</span>
              <input
                id="product-price"
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={form.price}
                onChange={(e) => update('price', e.target.value)}
                required
              />
            </label>

            <label className="field" htmlFor="product-purchase-price">
              <span>Purchase price</span>
              <input
                id="product-purchase-price"
                className="input"
                type="number"
                step="0.01"
                min="0"
                value={form.purchase_price}
                onChange={(e) => update('purchase_price', e.target.value)}
              />
            </label>

            <label className="field" htmlFor="product-gst">
              <span>GST rate (%)</span>
              <input
                id="product-gst"
                className="input"
                type="number"
                step="0.01"
                min="0"
                max="100"
                value={form.gst_rate}
                onChange={(e) => update('gst_rate', e.target.value)}
              />
            </label>

            <label className="field" htmlFor="product-hsn">
              <span>HSN / SAC</span>
              <input
                id="product-hsn"
                className="input"
                value={form.hsn_sac}
                onChange={(e) => update('hsn_sac', e.target.value)}
              />
            </label>

            <label className="field" htmlFor="product-unit">
              <span>Unit</span>
              <select
                id="product-unit"
                className="select"
                value={unitIsCustom ? CUSTOM_UNIT_VALUE : form.unit}
                onChange={(e) => {
                  if (e.target.value === CUSTOM_UNIT_VALUE) {
                    update('unit', CUSTOM_UNIT_VALUE);
                  } else {
                    setCustomUnit('');
                    update('unit', e.target.value);
                  }
                }}
              >
                {UNIT_OPTIONS.map((unit) => (
                  <option key={unit} value={unit}>
                    {unit}
                  </option>
                ))}
                <option value={CUSTOM_UNIT_VALUE}>Custom…</option>
              </select>
            </label>

            {unitIsCustom ? (
              <label className="field" htmlFor="product-custom-unit">
                <span>Custom unit name</span>
                <input
                  id="product-custom-unit"
                  className="input"
                  value={customUnit}
                  onChange={(e) => setCustomUnit(e.target.value)}
                  placeholder="Dozen"
                />
              </label>
            ) : null}

            <label className="field" htmlFor="product-reorder">
              <span>Reorder level</span>
              <input
                id="product-reorder"
                className="input"
                type="number"
                step="0.001"
                min="0"
                value={form.reorder_level}
                onChange={(e) => update('reorder_level', e.target.value)}
              />
              <p className="field-hint">
                Stock at or below this flags as low. Leave at 0 to never flag.
              </p>
            </label>

            <label className="field field--full" htmlFor="product-description">
              <span>Description</span>
              <textarea
                id="product-description"
                className="textarea"
                rows={2}
                value={form.description}
                onChange={(e) => update('description', e.target.value)}
              />
            </label>
          </div>

          <div className="form-section">
            <div className="form-section__header">
              <div>
                <p className="form-section__eyebrow">Behaviour</p>
                <h3 className="form-section__title">How this product is tracked</h3>
              </div>
            </div>

            <div className="stack">
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={form.maintain_inventory}
                  disabled={form.track_serials}
                  onChange={(e) => update('maintain_inventory', e.target.checked)}
                />
                <span>Maintain stock for this product</span>
              </label>
              <p className="field-hint">
                {form.track_serials
                  ? 'Required while serial tracking is on.'
                  : 'Off for services and anything you do not count.'}
              </p>

              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={form.allow_decimal}
                  disabled={form.track_serials}
                  onChange={(e) => update('allow_decimal', e.target.checked)}
                />
                <span>Allow fractional quantities</span>
              </label>
              <p className="field-hint">
                {form.track_serials
                  ? 'Unavailable: a serialised unit cannot be split.'
                  : 'For weights and lengths, e.g. 2.5 Kg.'}
              </p>

              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={form.track_serials}
                  onChange={(e) => setTrackSerials(e.target.checked)}
                />
                <span>Track individual serial numbers / IMEIs</span>
              </label>
              <p className="field-hint">
                Every unit is scanned in and out by its own identifier.
              </p>

              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={form.is_producable}
                  onChange={(e) => update('is_producable', e.target.checked)}
                />
                <span>This product is manufactured in-house</span>
              </label>
              <p className="field-hint">Producing it consumes its bill of materials.</p>

              {form.is_producable ? (
                <>
                  <label className="field" htmlFor="product-production-cost">
                    <span>Production cost</span>
                    <input
                      id="product-production-cost"
                      className="input"
                      type="number"
                      step="0.01"
                      min="0"
                      value={form.production_cost}
                      onChange={(e) => update('production_cost', e.target.value)}
                    />
                  </label>
                  {isEdit && row ? (
                    <button
                      type="button"
                      className="button button--ghost button--small"
                      onClick={() => onConfigureBom(row.id, row.name)}
                    >
                      <Settings2 size={15} aria-hidden="true" />
                      Configure bill of materials
                    </button>
                  ) : (
                    <p className="field-hint">
                      Save the product first, then set its bill of materials from the row menu.
                    </p>
                  )}
                </>
              ) : null}
            </div>
          </div>

          {!isEdit ? (
            <div className="form-section">
              <div className="form-section__header">
                <div>
                  <p className="form-section__eyebrow">Opening stock</p>
                  <h3 className="form-section__title">What is on the shelf today</h3>
                </div>
              </div>
              {form.track_serials ? (
                <>
                  <SerialChips
                    value={form.serial_numbers}
                    onChange={(next) => update('serial_numbers', next)}
                    productId={null}
                    mode="purchase"
                    idPrefix="product-form-serials"
                  />
                  <p className="field-hint">
                    Opening stock is the number of serials entered: {form.serial_numbers.length}.
                  </p>
                </>
              ) : (
                <label className="field" htmlFor="product-initial-qty">
                  <span>Opening quantity</span>
                  <input
                    id="product-initial-qty"
                    className="input"
                    type="number"
                    step={form.allow_decimal ? '0.001' : '1'}
                    min="0"
                    value={form.initial_quantity}
                    onChange={(e) => update('initial_quantity', e.target.value)}
                  />
                  <p className="field-hint">
                    After this, stock only moves through an audited adjustment.
                  </p>
                </label>
              )}
            </div>
          ) : null}

          {error ? (
            <p className="form-error" id={errorId} role="alert">
              {error}
            </p>
          ) : null}

          <div className="form-action-bar">
            <button type="button" className="button button--secondary" onClick={onCancel}>
              Cancel
            </button>
            <button
              type="submit"
              className={`button button--primary${submitting ? ' is-busy' : ''}`}
              disabled={submitting}
              aria-describedby={error ? errorId : undefined}
            >
              {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create product'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
