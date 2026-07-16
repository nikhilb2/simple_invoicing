import { useRef } from 'react';

/**
 * Accessible tab bar.
 *
 * Keeps the app's existing segmented-control look (button--primary for the
 * selected tab, button--ghost otherwise — the idiom TaxLedgerPage and
 * InvoicesAdvancedView already use by hand) while adding the ARIA roles and
 * arrow-key navigation those ad-hoc versions lack. They can adopt this later.
 */

export type TabItem<T extends string> = {
  id: T;
  label: string;
};

type TabsProps<T extends string> = {
  tabs: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Accessible name for the tablist. */
  label: string;
  /** id of the panel each tab controls, derived from the tab id. */
  panelId?: (id: T) => string;
};

export function tabPanelId(id: string) {
  return `tabpanel-${id}`;
}

export function tabId(id: string) {
  return `tab-${id}`;
}

export default function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  panelId = tabPanelId,
}: TabsProps<T>) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const focusTab = (id: T) => {
    onChange(id);
    refs.current[id]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const index = tabs.findIndex((tab) => tab.id === value);
    if (index === -1) return;

    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      // Wrap around, per the WAI-ARIA tabs pattern.
      focusTab(tabs[(index + offset + tabs.length) % tabs.length].id);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusTab(tabs[0].id);
    } else if (event.key === 'End') {
      event.preventDefault();
      focusTab(tabs[tabs.length - 1].id);
    }
  };

  return (
    <div className="tab-bar" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((tab) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            ref={(node) => { refs.current[tab.id] = node; }}
            id={tabId(tab.id)}
            role="tab"
            type="button"
            aria-selected={selected}
            aria-controls={panelId(tab.id)}
            // Roving tabindex: only the selected tab is in the tab order.
            tabIndex={selected ? 0 : -1}
            className={`button ${selected ? 'button--primary' : 'button--ghost'}`}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({
  id,
  children,
}: {
  id: string;
  children: React.ReactNode;
}) {
  return (
    <div className="tab-panel" role="tabpanel" id={tabPanelId(id)} aria-labelledby={tabId(id)} tabIndex={0}>
      {children}
    </div>
  );
}
