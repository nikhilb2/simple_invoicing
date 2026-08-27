import { useCallback, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowRight, PackageX, X } from 'lucide-react';
import api, { getApiErrorMessage } from '../../api/client';
import { track } from '../../lib/analytics';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import SerialChips from '../invoices/components/SerialChips';
import type { InventoryAdjust } from '../../types/api';
import { formatQuantity, isLowStock } from './types';
import type { CatalogueRow } from './types';

/**
 * The single stock-editing surface for the Catalogue.
 *
 * Stock is never written as an absolute number here — every change goes through
 * `POST /inventory/adjust` as a signed delta with a reason and, for a serialised
 * product, the units themselves. That endpoint is what records the movement, so
 * an absolute overwrite (what the old Products & Inventory page allowed) would
 * leave the ledger with a quantity nobody can account for.
 *
 * The adjustment rules are ported from InventoryPage's inline adjuster.
 */

type StockAdjustModalProps = {
  row: CatalogueRow;
  onCancel: () => void;
  /** Called after a successful adjustment so the list can refetch. */
  onAdjusted: (message: string) => void;
};

const TITLE_ID = 'stock-adjust-title';
const DELTA_ID = 'stock-adjust-delta';
const DELTA_HINT_ID = 'stock-adjust-delta-hint';
const DELTA_ERROR_ID = 'stock-adjust-delta-error';
const REASON_ID = 'stock-adjust-reason';
const REASON_HINT_ID = 'stock-adjust-reason-hint';
const FORM_ERROR_ID = 'stock-adjust-form-error';

/** A delta always carries its sign, so "+4" and "-4" read apart at a glance. */
function formatDelta(delta: number, allowDecimal: boolean): string {
  const magnitude = formatQuantity(Math.abs(delta), allowDecimal);
  return `${delta < 0 ? '-' : '+'}${magnitude}`;
}

export default function StockAdjustModal({ row, onCancel, onAdjusted }: StockAdjustModalProps) {
  const [deltaInput, setDeltaInput] = useState('');
  const [reason, setReason] = useState('');
  const [serials, setSerials] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');

  // Dismissing mid-flight would discard the outcome of a request that is still
  // going to land, so Escape and the overlay only close while idle.
  const dismiss = useCallback(() => {
    if (!submitting) onCancel();
  }, [submitting, onCancel]);

  useEscapeClose(dismiss);

  const trimmedDelta = deltaInput.trim();
  const parsedDelta = Number(trimmedDelta);
  // Number('') is 0, so an empty box has to be excluded before the parse counts.
  const hasDelta = trimmedDelta !== '' && Number.isFinite(parsedDelta) && parsedDelta !== 0;
  const newQuantity = hasDelta ? row.current_stock + parsedDelta : row.current_stock;

  /**
   * How many serials this adjustment must name. Ported from InventoryPage: an
   * untracked product needs none, and a half-typed delta ("-", "1e") parses to
   * NaN and requires none until it resolves to a number.
   */
  const unitsRequired = row.track_serials && Number.isFinite(parsedDelta)
    ? Math.abs(Math.trunc(parsedDelta))
    : 0;

  const deltaError = (() => {
    if (trimmedDelta === '') return '';
    if (!Number.isFinite(parsedDelta)) return 'Enter a number — positive adds stock, negative removes it.';
    if (parsedDelta === 0) return 'A change of zero would not move any stock.';
    if (!row.allow_decimal && !Number.isInteger(parsedDelta)) {
      return `${row.name} is counted in whole ${row.unit} — enter a whole number.`;
    }
    // A serial is a physical unit; half of one cannot be scanned, so a
    // fractional delta could never be matched by a serial count.
    if (row.track_serials && !Number.isInteger(parsedDelta)) {
      return 'Serial-tracked stock moves one whole unit at a time.';
    }
    // Caught here rather than left to the server: the user should know the
    // adjustment is impossible before spending time scanning units for it.
    if (row.current_stock + parsedDelta < 0) {
      return `Only ${formatQuantity(row.current_stock, row.allow_decimal)} ${row.unit} on hand — you cannot remove more than that.`;
    }
    return '';
  })();

  /**
   * A reason is what makes the movement auditable, and a removal is the case
   * where that matters: stock leaving outside a sale is a write-off, damage or
   * a correction, and none of those are self-explanatory later. An increase
   * names its own cause well enough (a receipt, a found unit), so the reason
   * stays optional there rather than becoming a box people fill with "stock".
   */
  const reasonRequired = hasDelta && parsedDelta < 0;
  const reasonMissing = reasonRequired && reason.trim() === '';

  const serialsComplete = unitsRequired === 0 || serials.length === unitsRequired;

  const canSubmit =
    row.maintain_inventory &&
    hasDelta &&
    deltaError === '' &&
    !reasonMissing &&
    serialsComplete &&
    !submitting;

  function handleDeltaChange(next: string) {
    // Units scanned for an increase are not the units of a write-off, so a
    // flip of the sign invalidates whatever has already been scanned.
    if (Math.sign(Number(next)) !== Math.sign(Number(deltaInput || '0'))) {
      setSerials([]);
    }
    setDeltaInput(next);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Enter in a field and a click on the button can both fire before the first
    // request resolves; the flag makes the second one a no-op.
    if (submitting || !canSubmit) return;

    // Re-asserted at the point of send rather than trusted from the render
    // above — a product with inventory switched off has no quantity to move.
    if (!row.maintain_inventory) {
      setSubmitError(`Inventory is not maintained for ${row.name}. Enable Maintain inventory on the product first.`);
      return;
    }
    if (row.track_serials && serials.length !== Math.abs(parsedDelta)) {
      setSubmitError(
        `${row.name} is serial tracked — scan ${Math.abs(parsedDelta)} serial number${Math.abs(parsedDelta) === 1 ? '' : 's'} for this adjustment.`,
      );
      return;
    }

    const note = reason.trim();

    try {
      setSubmitting(true);
      setSubmitError('');
      const payload: InventoryAdjust = {
        product_id: row.id,
        quantity: parsedDelta,
        ...(row.track_serials ? { serial_numbers: serials } : {}),
        ...(note ? { note } : {}),
      };
      await api.post('/inventory/adjust', payload);
      track('inventory_adjusted', {
        product_id: row.id,
        direction: parsedDelta > 0 ? 'increase' : 'decrease',
        source: 'catalogue',
      });
      onAdjusted(
        `${row.name}: ${formatQuantity(row.current_stock, row.allow_decimal)} → ${formatQuantity(newQuantity, row.allow_decimal)} (${formatDelta(parsedDelta, row.allow_decimal)}).`,
      );
    } catch (err) {
      // Stays open and keeps every typed value — a failed adjustment must not
      // cost the user a scan of twenty serials.
      setSubmitError(getApiErrorMessage(err, 'Unable to adjust stock'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby={TITLE_ID}
      onClick={dismiss}
    >
      <div className="modal-panel modal-panel--stock-adjust" onClick={(event) => event.stopPropagation()}>
        <div className="panel__header">
          <h2 id={TITLE_ID} className="nav-panel__title">Adjust stock</h2>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={dismiss}
            disabled={submitting}
            title="Close"
            aria-label="Close stock adjustment"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="stock-adjust__summary">
          <div className="stock-adjust__identity">
            <strong className="stock-adjust__name">{row.name}</strong>
            <span className="stock-adjust__sku">
              {row.sku} • Unit {row.unit}
              {row.track_serials ? ' • Serialised' : ''}
            </span>
          </div>
          <span className={`pill ${isLowStock(row) ? 'pill--low' : 'pill--ok'}`}>
            {formatQuantity(row.current_stock, row.allow_decimal)}
          </span>
        </div>
        <p className="field-hint stock-adjust__on-hand">On hand now</p>

        {!row.maintain_inventory ? (
          <>
            {/* Nothing to adjust: with inventory off the product carries no
                stock figure, so offering a delta would imply one exists. */}
            <p className="stock-adjust__notice">
              <PackageX size={16} aria-hidden="true" />
              <span>
                Stock is not maintained for {row.name}. Turn on Maintain inventory in the product's
                settings to track and adjust its quantity.
              </span>
            </p>
            <div className="form-action-bar">
              <button
                type="button"
                className="button button--primary"
                onClick={onCancel}
                title="Close"
                aria-label="Close stock adjustment"
              >
                Close
              </button>
            </div>
          </>
        ) : (
          <form className="stack" onSubmit={(event) => void handleSubmit(event)}>
            <div className="field">
              <label htmlFor={DELTA_ID}>Change</label>
              <input
                id={DELTA_ID}
                className="input"
                type="number"
                inputMode="decimal"
                step={row.allow_decimal ? '0.001' : '1'}
                autoFocus
                placeholder={row.allow_decimal ? 'e.g. -2.5' : 'e.g. -3'}
                value={deltaInput}
                onChange={(event) => handleDeltaChange(event.target.value)}
                disabled={submitting}
                aria-describedby={deltaError ? `${DELTA_HINT_ID} ${DELTA_ERROR_ID}` : DELTA_HINT_ID}
                aria-invalid={deltaError ? true : undefined}
              />
              <p id={DELTA_HINT_ID} className="field-hint">
                A positive number adds stock, a negative number removes it
                {row.allow_decimal ? '. Fractions are allowed for this product.' : '. Whole units only.'}
              </p>
              {hasDelta && !deltaError ? (
                <p className="stock-adjust__preview" aria-live="polite">
                  <span className="stock-adjust__preview-from">
                    {formatQuantity(row.current_stock, row.allow_decimal)}
                  </span>
                  <ArrowRight size={14} aria-hidden="true" />
                  <span className="stock-adjust__preview-to">
                    {formatQuantity(newQuantity, row.allow_decimal)}
                  </span>
                  <span
                    className={`stock-adjust__preview-delta${parsedDelta < 0 ? ' stock-adjust__preview-delta--down' : ''}`}
                  >
                    ({formatDelta(parsedDelta, row.allow_decimal)})
                  </span>
                </p>
              ) : null}
              {deltaError ? (
                <p id={DELTA_ERROR_ID} className="stock-adjust__error" role="alert">
                  {deltaError}
                </p>
              ) : null}
            </div>

            <div className="field">
              <label htmlFor={REASON_ID}>
                Reason{reasonRequired ? '' : ' (optional)'}
              </label>
              <input
                id={REASON_ID}
                className="input"
                type="text"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                disabled={submitting}
                placeholder={parsedDelta < 0 ? 'e.g. Damaged in transit' : 'e.g. Found in back store'}
                aria-describedby={REASON_HINT_ID}
                aria-invalid={reasonMissing ? true : undefined}
              />
              <p id={REASON_HINT_ID} className={reasonMissing ? 'stock-adjust__error' : 'field-hint'}>
                {reasonRequired
                  ? 'Required for a removal — a write-off needs a why on the record.'
                  : 'Recorded against the movement so the change can be accounted for later.'}
              </p>
            </div>

            {/* A serialised adjustment cannot be applied from the number alone
                — the units themselves have to be named. */}
            {unitsRequired > 0 ? (
              <div className="serial-line">
                <p
                  className={`serial-backfill__counter${serials.length === unitsRequired ? ' serial-backfill__counter--complete' : ''}`}
                  aria-live="polite"
                >
                  {serials.length}
                  <span className="serial-backfill__counter-total">of {unitsRequired} scanned</span>
                </p>
                <SerialChips
                  value={serials}
                  onChange={setSerials}
                  productId={row.id}
                  mode={parsedDelta > 0 ? 'purchase' : 'sales'}
                  disabled={submitting}
                  idPrefix="stock-adjust-serials"
                />
              </div>
            ) : null}

            {submitError ? (
              <p id={FORM_ERROR_ID} className="stock-adjust__error" role="alert">
                {submitError}
              </p>
            ) : null}

            <div className="form-action-bar">
              <p className="form-action-bar__meta">Recorded as an audited movement.</p>
              <button
                type="button"
                className="button button--secondary"
                onClick={onCancel}
                disabled={submitting}
                title="Cancel"
                aria-label="Cancel stock adjustment"
              >
                Cancel
              </button>
              <button
                type="submit"
                className={`button button--primary${submitting ? ' is-busy' : ''}`}
                disabled={!canSubmit}
                title="Apply adjustment"
                aria-label={`Apply stock adjustment for ${row.name}`}
                aria-describedby={submitError ? FORM_ERROR_ID : undefined}
              >
                {submitting ? 'Applying…' : 'Apply adjustment'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
