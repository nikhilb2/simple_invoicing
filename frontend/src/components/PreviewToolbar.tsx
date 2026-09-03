import { ReactNode, useCallback, useEffect, useRef } from 'react';
import { MoreHorizontal } from 'lucide-react';
import ModalCloseButton from './ModalCloseButton';

export type PreviewAction = {
  label: string;
  icon: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  /** Falls back to `label` for the tooltip and the accessible name. */
  title?: string;
};

type PreviewToolbarProps = {
  eyebrow: string;
  title: string;
  titleId: string;
  meta?: ReactNode;
  /** The one filled button. Everything else is quiet on purpose. */
  primary: PreviewAction;
  /**
   * Shown as quiet (ghost) buttons beside the primary. Keep to two — past that,
   * use the menu. They are deliberately not `--secondary`: that variant is a
   * solid blue gradient, so three filled buttons in a row read as three
   * competing primaries, which is the clutter this component exists to remove.
   */
  secondary?: PreviewAction[];
  /** Behind the "…" button. Low-frequency actions belong here, not in the row. */
  menu?: PreviewAction[];
  /** Rendered above the menu items — for a setting rather than an action. */
  menuExtra?: ReactNode;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  onClose: () => void;
  closeLabel: string;
};

/**
 * The header of a document preview: what you are looking at, then what you can
 * do with it.
 *
 * Shared by the invoice, receipt and statement previews so the same action sits
 * in the same place in all three. Each had grown its own row of five or six
 * equally loud buttons, which is what made them read as clutter — the fix is
 * one filled action, the rest quiet, the rare ones folded away, and the close
 * affordance pulled out of the row entirely and into the corner where a dialog
 * close belongs.
 */
export default function PreviewToolbar({
  eyebrow,
  title,
  titleId,
  meta,
  primary,
  secondary = [],
  menu = [],
  menuExtra,
  menuOpen,
  onMenuOpenChange,
  onClose,
  closeLabel,
}: PreviewToolbarProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onMenuOpenChange(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpen, onMenuOpenChange]);

  const runAndClose = useCallback((action: PreviewAction) => {
    onMenuOpenChange(false);
    action.onClick();
  }, [onMenuOpenChange]);

  const hasMenu = menu.length > 0 || Boolean(menuExtra);

  return (
    <div className="panel__header preview-header no-print">
      <div className="preview-header__title">
        <p className="eyebrow">{eyebrow}</p>
        <h2 id={titleId} className="nav-panel__title">{title}</h2>
        {meta ? <p className="muted-text preview-header__meta">{meta}</p> : null}
      </div>

      <div className="preview-header__actions">
        <div className="button-row preview-toolbar">
          <button
            type="button"
            className="button button--primary"
            onClick={primary.onClick}
            disabled={primary.disabled}
            title={primary.title ?? primary.label}
            aria-label={primary.title ?? primary.label}
          >
            {primary.icon}
            {primary.label}
          </button>

          {secondary.map((action) => (
            <button
              key={action.label}
              type="button"
              className="button button--ghost"
              onClick={action.onClick}
              disabled={action.disabled}
              title={action.title ?? action.label}
              aria-label={action.title ?? action.label}
            >
              {action.icon}
              {action.label}
            </button>
          ))}

          {hasMenu ? (
            <div className="action-dropdown" ref={menuRef}>
              <button
                type="button"
                className="button button--ghost button--icon"
                onClick={() => onMenuOpenChange(!menuOpen)}
                aria-haspopup="true"
                aria-expanded={menuOpen}
                title="More actions"
                aria-label="More actions"
              >
                <MoreHorizontal size={16} aria-hidden="true" />
              </button>
              {menuOpen ? (
                <div className="action-dropdown__menu" role="menu">
                  {menuExtra}
                  {menu.map((action) => (
                    <button
                      key={action.label}
                      type="button"
                      className="action-dropdown__item"
                      role="menuitem"
                      onClick={() => runAndClose(action)}
                      disabled={action.disabled}
                      aria-label={action.title ?? action.label}
                    >
                      {action.icon}
                      {action.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <ModalCloseButton onClick={onClose} label={closeLabel} />
      </div>
    </div>
  );
}
