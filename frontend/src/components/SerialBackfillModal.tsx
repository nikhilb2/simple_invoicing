import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import { useEscapeClose } from '../hooks/useEscapeClose';
import ModalCloseButton from './ModalCloseButton';
import SerialChips from '../pages/invoices/components/SerialChips';
import { fetchAvailableSerials } from '../features/serials/api';
import type { ProductCreate } from '../types/api';

type SerialBackfillModalProps = {
  productId: number;
  productName: string;
  /** Stock is fetched by SKU — the products list carries no quantity. */
  productSku: string;
  /**
   * The rest of the product edit, saved together with the flag and the serials:
   * one PUT means a product can never end up tracked with fewer units than it
   * has in stock.
   */
  payload: ProductCreate;
  onSaved: () => void;
  onCancel: () => void;
};

function splitPasted(raw: string) {
  return raw.split(/[\s,;]+/).map((entry) => entry.trim()).filter(Boolean);
}

export default function SerialBackfillModal({
  productId,
  productName,
  productSku,
  payload,
  onSaved,
  onCancel,
}: SerialBackfillModalProps) {
  const [serials, setSerials] = useState<string[]>([]);
  const [pasted, setPasted] = useState('');
  const [required, setRequired] = useState<number | null>(null);
  const [onHand, setOnHand] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEscapeClose(onCancel);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        setError('');
        const [stockRes, covered] = await Promise.all([
          api.get<{ items: Array<{ id: number; current_stock: number }> }>('/products/with-inventory', {
            params: { search: productSku, page_size: 200 },
          }),
          /* Tracking can be switched off and back on, so some units on the
             shelf may already carry a serial from the first time round. Only
             the uncovered ones are owed. */
          fetchAvailableSerials({ productId, pageSize: 1 }),
        ]);
        if (cancelled) return;

        const row = stockRes.data.items.find((item) => item.id === productId);
        const stock = Math.max(Math.trunc(row?.current_stock ?? 0), 0);
        setOnHand(stock);
        setRequired(Math.max(stock - covered.total, 0));
      } catch (err) {
        if (cancelled) return;
        setError(getApiErrorMessage(err, 'Unable to read the current stock for this product.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [productId, productSku]);

  function addPasted() {
    if (required === null) return;

    const candidates = splitPasted(pasted);
    if (candidates.length === 0) return;

    const seen = new Set(serials.map((entry) => entry.toUpperCase()));
    const fresh: string[] = [];
    for (const candidate of candidates) {
      const key = candidate.toUpperCase();
      if (seen.has(key)) continue;
      seen.add(key);
      fresh.push(candidate);
    }

    if (fresh.length === 0) {
      setError('Every serial in that list is already on the sheet.');
      return;
    }
    if (serials.length + fresh.length > required) {
      setError(`That is ${serials.length + fresh.length} serials for ${required} units — trim the list and paste again.`);
      return;
    }

    /* Pasted codes skip the per-serial check the chips input runs: a hundred
       lookups for one paste is not worth it, and the save names any code that
       is already registered elsewhere. */
    setSerials([...serials, ...fresh]);
    setPasted('');
    setError('');
  }

  async function handleSave() {
    try {
      setSaving(true);
      setError('');
      const body: ProductCreate = { ...payload, track_serials: true, serial_numbers: serials };
      await api.put(`/products/${productId}`, body);
      onSaved();
    } catch (err) {
      const message = getApiErrorMessage(err, 'Unable to turn on serial tracking.');
      /* The backend owns the count — a product whose tracking was switched off
         and on again already covers some of its units. If it says a different
         number, its answer wins and the counter retargets. */
      const owed = message.match(/provide (\d+) serial number/);
      if (owed) {
        setRequired(Number(owed[1]));
      }
      setError(message);
    } finally {
      setSaving(false);
    }
  }

  const complete = required !== null && serials.length === required;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="serial-backfill-title">
      <div className="modal-panel">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Serial tracking</p>
            <h2 id="serial-backfill-title" className="nav-panel__title">Enter the serials already in stock</h2>
          </div>
          <ModalCloseButton onClick={onCancel} label="Close serial entry" />
        </div>

        <div className="serial-backfill">
          {loading ? <p className="serial-backfill__intro">Checking how many units are on the shelf…</p> : null}

          {!loading && required !== null ? (
            <p className="serial-backfill__intro">
              {required === 0
                ? `${productName} has ${onHand} unit${onHand === 1 ? '' : 's'} in stock and every one of them already has a serial. Nothing to enter.`
                : onHand > required
                  ? `${productName} has ${onHand} units in stock and ${onHand - required} already carry a serial. Enter the IMEI for the remaining ${required} so nothing goes untracked.`
                  : `${productName} has ${onHand} unit${onHand === 1 ? '' : 's'} in stock. Enter the IMEI for each one so nothing goes untracked.`}
            </p>
          ) : null}

          {!loading && required !== null && required > 0 ? (
            <>
              <p
                className={`serial-backfill__counter${complete ? ' serial-backfill__counter--complete' : ''}`}
                aria-live="polite"
              >
                {serials.length}
                <span className="serial-backfill__counter-total">/ {required} entered</span>
              </p>

              <SerialChips
                value={serials}
                onChange={(next) => { setSerials(next); setError(''); }}
                productId={productId}
                mode="purchase"
                disabled={saving}
                idPrefix="serial-backfill"
              />

              <div className="serial-backfill__paste">
                <label className="serial-chips__label" htmlFor="serial-backfill-paste">Or paste a list</label>
                <textarea
                  id="serial-backfill-paste"
                  className="textarea"
                  rows={3}
                  spellCheck={false}
                  value={pasted}
                  disabled={saving}
                  onChange={(event) => { setPasted(event.target.value); setError(''); }}
                  placeholder="One per line, or separated by commas"
                />
                <div className="button-row">
                  <button
                    type="button"
                    className="button button--ghost button--small"
                    disabled={saving || !pasted.trim()}
                    onClick={addPasted}
                    title="Add pasted serials"
                    aria-label="Add pasted serials"
                  >
                    Add pasted serials
                  </button>
                </div>
              </div>
            </>
          ) : null}

          {error ? <p className="serial-backfill__error" role="alert">{error}</p> : null}

          <div className="button-row">
            <button
              type="button"
              className="button button--ghost"
              onClick={onCancel}
              disabled={saving}
              title="Cancel serial tracking"
              aria-label="Cancel serial tracking"
            >
              Cancel
            </button>
            <button
              type="button"
              className="button button--primary"
              onClick={() => void handleSave()}
              disabled={loading || saving || !complete}
              title="Turn on serial tracking"
              aria-label="Turn on serial tracking"
            >
              {saving ? 'Saving…' : 'Turn on serial tracking'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
