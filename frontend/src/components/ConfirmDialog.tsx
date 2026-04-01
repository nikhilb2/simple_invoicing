import type { ReactNode } from 'react';

type ConfirmDialogProps = {
  /** Message to display in the dialog */
  message: string;
  /** Called when user confirms the action */
  onConfirm: () => void;
  /** Called when user cancels the action */
  onCancel: () => void;
  /** Optional custom title for the dialog */
  title?: string;
  /** Optional custom confirm button text (defaults to "Delete") */
  confirmText?: string;
  /** Optional custom cancel button text (defaults to "Cancel") */
  cancelText?: string;
  /** Optional danger level - affects confirm button styling */
  danger?: boolean;
};

/**
 * A reusable confirmation dialog component.
 * Displays a modal with a message and Cancel/Confirm buttons.
 * Used for confirming destructive actions like delete.
 */
export default function ConfirmDialog({
  message,
  onConfirm,
  onCancel,
  title = 'Confirm action',
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  danger = false,
}: ConfirmDialogProps) {
  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-message"
      onClick={onCancel}
    >
      <div
        className="modal-panel"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '400px' }}
      >
        <div className="panel__header">
          <h2 id="confirm-dialog-title" className="nav-panel__title">{title}</h2>
        </div>
        <p id="confirm-dialog-message" style={{ margin: '16px 0' }}>{message}</p>
        <div className="button-row" style={{ justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            className="button button--secondary"
            onClick={onCancel}
          >
            {cancelText}
          </button>
          <button
            type="button"
            className={`button ${danger ? 'button--danger' : 'button--primary'}`}
            onClick={onConfirm}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}