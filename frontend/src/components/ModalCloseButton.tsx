import { X } from 'lucide-react';

type ModalCloseButtonProps = {
  onClick: () => void;
  /** What this closes, e.g. "Close create ledger" — read out instead of a bare "Close". */
  label: string;
  /** Set while a submit is in flight, so the dialog cannot be closed mid-write. */
  disabled?: boolean;
};

/**
 * The one way out of a dialog. It belongs in the .panel__header, which every
 * modal pins to the top of its scroll area, so a user part-way down a long form
 * never has to scroll back to Cancel to get out.
 */
export default function ModalCloseButton({ onClick, label, disabled = false }: ModalCloseButtonProps) {
  return (
    <button
      type="button"
      className="button button--ghost button--icon"
      onClick={onClick}
      disabled={disabled}
      title="Close"
      aria-label={label}
    >
      <X size={16} aria-hidden="true" />
    </button>
  );
}
