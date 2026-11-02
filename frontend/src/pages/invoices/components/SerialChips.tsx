import { useState } from 'react';
import { ListPlus, X } from 'lucide-react';
import { getApiErrorMessage } from '../../../api/client';
import { scanCode } from '../../../features/serials/api';
import { formatInvoiceDateLabel } from '../../../utils/invoiceDueDate.ts';

type SerialChipsProps = {
  value: string[];
  onChange: (next: string[]) => void;
  /** The product the serials must belong to. Null while no product is chosen. */
  productId: number | null;
  /** Sales consumes existing in-stock serials; purchase registers new ones. */
  mode: 'sales' | 'purchase';
  disabled?: boolean;
  /** Unique per rendering site — this component appears once per line item. */
  idPrefix: string;
  /** Renders the "Pick from stock" action when the caller can open a picker. */
  onPickFromStock?: () => void;
};

function sameSerial(a: string, b: string) {
  return a.trim().toUpperCase() === b.trim().toUpperCase();
}

export default function SerialChips({
  value,
  onChange,
  productId,
  mode,
  disabled = false,
  idPrefix,
  onPickFromStock,
}: SerialChipsProps) {
  const [draft, setDraft] = useState('');
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');

  function removeSerial(serial: string) {
    onChange(value.filter((entry) => entry !== serial));
  }

  /**
   * Validates against the same endpoint the scan bar uses, so a typed serial
   * and a scanned one are held to identical rules — a sold IMEI is refused by
   * name whichever way it arrived.
   */
  async function addSerial(raw: string) {
    const candidate = raw.trim();
    if (!candidate) return;

    if (value.some((entry) => sameSerial(entry, candidate))) {
      setError('Already on this line.');
      return;
    }

    try {
      setChecking(true);
      setError('');
      const lookup = await scanCode(candidate);

      if (mode === 'purchase') {
        if (!lookup.found) {
          onChange([...value, candidate]);
          setDraft('');
          return;
        }
        setError(
          lookup.result.kind === 'serial'
            ? `${lookup.result.serial.serial_number} is already registered to ${lookup.result.serial.product.name}.`
            : 'That is a product code, not a serial number.',
        );
        return;
      }

      if (!lookup.found) {
        setError(lookup.detail);
        return;
      }
      if (lookup.result.kind !== 'serial') {
        setError('That is a product code, not a serial number.');
        return;
      }

      const serial = lookup.result.serial;
      if (serial.status === 'sold') {
        const ref = serial.sales_invoice;
        setError(
          ref
            ? `Already sold on ${ref.invoice_number ?? `#${ref.id}`} (${formatInvoiceDateLabel(ref.invoice_date)}).`
            : 'This serial is already sold.',
        );
        return;
      }
      if (productId !== null && serial.product_id !== productId) {
        setError(`${serial.serial_number} belongs to ${serial.product.name}.`);
        return;
      }

      onChange([...value, serial.serial_number]);
      setDraft('');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to check that serial number.'));
    } finally {
      setChecking(false);
    }
  }

  const inputId = `${idPrefix}-serial-input`;

  return (
    <div className="serial-chips">
      <p className="serial-chips__count">Serials ({value.length})</p>

      {value.length > 0 ? (
        <ul className="serial-chips__list">
          {value.map((serial) => (
            <li key={serial} className="serial-chip">
              <span className="serial-chip__value">{serial}</span>
              {!disabled ? (
                <button
                  type="button"
                  className="serial-chip__remove"
                  onClick={() => removeSerial(serial)}
                  title={`Remove ${serial}`}
                  aria-label={`Remove serial ${serial}`}
                >
                  <X size={12} aria-hidden="true" />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="serial-chips__entry">
        <label className="serial-chips__label" htmlFor={inputId}>
          {mode === 'purchase' ? 'Scan or type a serial to register' : 'Scan or type a serial'}
        </label>
        <div className="serial-chips__entry-row">
          <input
            id={inputId}
            className="input"
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={draft}
            disabled={disabled || checking}
            placeholder="e.g. 356938035643809"
            onChange={(event) => { setDraft(event.target.value); setError(''); }}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return;
              // Enter here means "add this serial", never "create the invoice".
              event.preventDefault();
              void addSerial(draft);
            }}
          />
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={disabled || checking || !draft.trim()}
            onClick={() => { void addSerial(draft); }}
          >
            {checking ? 'Checking…' : 'Add'}
          </button>
          {onPickFromStock ? (
            <button
              type="button"
              className="button button--ghost button--small"
              disabled={disabled || productId === null}
              onClick={onPickFromStock}
            >
              <ListPlus size={13} aria-hidden="true" />
              Pick from stock
            </button>
          ) : null}
        </div>
        {error ? <p className="serial-chips__error" role="alert">{error}</p> : null}
      </div>
    </div>
  );
}
