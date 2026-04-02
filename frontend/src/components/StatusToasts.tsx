import { useEffect } from 'react';

type ToastKind = 'success' | 'error';

type ToastProps = {
  kind: ToastKind;
  message: string;
  onDismiss: () => void;
};

type StatusToastsProps = {
  error?: string;
  success?: string;
  onClearError: () => void;
  onClearSuccess: () => void;
  successDurationMs?: number;
};

function Toast({ kind, message, onDismiss }: ToastProps) {
  const title = kind === 'success' ? 'Success notification' : 'Error notification';

  return (
    <div className={`toast toast--${kind}`} role={kind === 'error' ? 'alert' : 'status'} aria-live={kind === 'error' ? 'assertive' : 'polite'}>
      <div className="toast__content">
        <strong className="toast__title">{title}</strong>
        <span className="toast__message">{message}</span>
      </div>
      <button
        type="button"
        className="toast__dismiss"
        onClick={onDismiss}
        aria-label={`Dismiss ${kind} notification`}
        title="Dismiss notification"
      >
        ×
      </button>
    </div>
  );
}

export default function StatusToasts({
  error,
  success,
  onClearError,
  onClearSuccess,
  successDurationMs = 5000,
}: StatusToastsProps) {
  useEffect(() => {
    if (!success) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      onClearSuccess();
    }, successDurationMs);

    return () => window.clearTimeout(timeoutId);
  }, [success, successDurationMs, onClearSuccess]);

  if (!error && !success) {
    return null;
  }

  return (
    <div className="toast-stack" aria-live="polite" aria-atomic="true">
      {error ? <Toast kind="error" message={error} onDismiss={onClearError} /> : null}
      {success ? <Toast kind="success" message={success} onDismiss={onClearSuccess} /> : null}
    </div>
  );
}
