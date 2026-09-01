import { useEffect, useRef, useState } from 'react';
import ModalCloseButton from '../../../components/ModalCloseButton';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import type { MarketplaceOrder, RejectOrderPayload } from '../../../features/marketplace/types';

const REASONS: { value: RejectOrderPayload['reason']; label: string }[] = [
  { value: 'insufficient_stock', label: 'Insufficient stock' },
  { value: 'price_changed', label: 'Price has changed' },
  { value: 'cannot_ship', label: 'Cannot ship to this buyer' },
  { value: 'unknown_buyer', label: 'Unknown buyer' },
  { value: 'other', label: 'Other' },
];

type RejectOrderModalProps = {
  order: MarketplaceOrder;
  submitting: boolean;
  error: string;
  onClose: () => void;
  onConfirm: (payload: RejectOrderPayload) => void;
};

/** The reason is not free text: it is part of the contract and the buyer's UI
 *  renders it ("Seller could not fulfil — out of stock"). */
export default function RejectOrderModal({ order, submitting, error, onClose, onConfirm }: RejectOrderModalProps) {
  const [reason, setReason] = useState<RejectOrderPayload['reason']>('insufficient_stock');
  const [note, setNote] = useState('');
  const selectRef = useRef<HTMLSelectElement>(null);

  useEscapeClose(onClose);
  useEffect(() => { selectRef.current?.focus(); }, []);

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="marketplace-reject-title"
      onClick={onClose}
    >
      <div className="modal-panel" style={{ maxWidth: '440px' }} onClick={(event) => event.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Reject order</p>
            <h2 id="marketplace-reject-title" className="nav-panel__title">{order.remote_order_id}</h2>
          </div>
          <ModalCloseButton onClick={onClose} label="Close reject order" />
        </div>

        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            onConfirm({ reason, note: note.trim() || undefined });
          }}
        >
          <div className="field">
            <label htmlFor="marketplace-reject-reason">Reason</label>
            <select
              id="marketplace-reject-reason"
              ref={selectRef}
              className="input"
              value={reason}
              onChange={(event) => setReason(event.target.value as RejectOrderPayload['reason'])}
            >
              {REASONS.map((entry) => (
                <option key={entry.value} value={entry.value}>{entry.label}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="marketplace-reject-note">Note to the buyer (optional)</label>
            <textarea
              id="marketplace-reject-note"
              className="input textarea"
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>

          <p className="marketplace-note">
            Rejecting releases the buyer's reservation. Neither side posts an invoice.
          </p>

          {error && <p className="marketplace-note marketplace-note--error">{error}</p>}

          <div className="button-row" style={{ justifyContent: 'flex-end' }}>
            <button type="button" className="button button--ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="button button--danger" disabled={submitting}>
              {submitting ? 'Rejecting…' : 'Reject order'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
