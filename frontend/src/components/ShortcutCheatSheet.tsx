import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useShortcuts } from '../context/ShortcutsContext';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { ACTION_KEYS, ACTION_LABELS } from '../utils/shortcutDefaults';
import ModalCloseButton from './ModalCloseButton';

type ShortcutCheatSheetProps = {
  onClose: () => void;
};

/**
 * Every shortcut with the key it is on right now — the user's own binding if
 * they changed it on the Keyboard Shortcuts page, otherwise the default.
 */
export default function ShortcutCheatSheet({ onClose }: ShortcutCheatSheetProps) {
  const { shortcutFor } = useShortcuts();
  const panelRef = useRef<HTMLDivElement>(null);
  useEscapeClose(onClose);

  // Opened from the keyboard, so put focus inside the dialog and hand it back
  // to whatever had it once the sheet goes away.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => previous?.focus?.();
  }, []);

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcut-cheat-sheet-title"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        className="modal-panel shortcut-cheat-sheet"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel__header">
          <h2 id="shortcut-cheat-sheet-title" className="nav-panel__title">Keyboard shortcuts</h2>
          <ModalCloseButton onClick={onClose} label="Close keyboard shortcuts" />
        </div>
        <dl className="shortcut-cheat-sheet__list">
          {ACTION_KEYS.map((key) => (
            <div key={key} className="shortcut-cheat-sheet__row">
              <dt>{ACTION_LABELS[key]}</dt>
              <dd><kbd>{shortcutFor(key)}</kbd></dd>
            </div>
          ))}
        </dl>
        <p className="shortcut-cheat-sheet__footer">
          <Link to="/settings/shortcuts" onClick={onClose}>Customise shortcuts</Link>
        </p>
      </div>
    </div>
  );
}
