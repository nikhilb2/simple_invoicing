import { useVersionCheck } from '../features/appVersion/useVersionCheck';

/**
 * Mounted once in Layout. Watches the build stamp and offers a reload when the
 * server is serving a newer build than this tab is running.
 *
 * Sits bottom-right rather than in the top-right `.toast-stack` that pages mount
 * for their own success/error toasts — both are `position: fixed` at the same
 * coordinates, so sharing the corner would overlap them.
 */
export default function UpdateAvailableToast() {
  const { updateVersion, dismiss } = useVersionCheck();

  if (!updateVersion) {
    return null;
  }

  return (
    <div className="toast-stack toast-stack--app" aria-live="polite" aria-atomic="true">
      <div className="toast toast--update" role="status">
        <div className="toast__content">
          <strong className="toast__title">Update available</strong>
          <span className="toast__message">
            A new version of Simple Invoicing is ready.
          </span>
          <button
            type="button"
            className="toast__action"
            onClick={() => window.location.reload()}
          >
            Reload now
          </button>
        </div>
        <button
          type="button"
          className="toast__dismiss"
          onClick={dismiss}
          aria-label="Dismiss update notification"
          title="Dismiss notification"
        >
          ×
        </button>
      </div>
    </div>
  );
}
