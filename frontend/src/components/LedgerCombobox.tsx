import { useEffect, useRef, useState } from 'react';
import type { Ledger } from '../types/api';

type LedgerComboboxProps = {
  id: string;
  ledgers: Ledger[];
  value: string; // ledger id as string
  onChange: (ledgerId: string) => void;
  required?: boolean;
  disabled?: boolean;
};

export default function LedgerCombobox({ id, ledgers, value, onChange, required, disabled }: LedgerComboboxProps) {
  const formatLedgerLabel = (ledger: Ledger) => ledger.gst ? `${ledger.name} (${ledger.gst})` : ledger.name;
  const formatSearchText = (ledger: Ledger) => `${ledger.name} ${ledger.gst || ''}`.toLowerCase();
  const selectedLedger = ledgers.find((l) => String(l.id) === value);
  const [query, setQuery] = useState(selectedLedger ? formatLedgerLabel(selectedLedger) : '');
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searching, setSearching] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Sync label when external value changes (e.g. default ledger on load)
  useEffect(() => {
    const l = ledgers.find((ledger) => String(ledger.id) === value);
    if (l) setQuery(formatLedgerLabel(l));
  }, [value, ledgers]);

  const suggestions = open
    ? ledgers.filter((l) =>
        searching && query.trim() !== ''
          ? formatSearchText(l).includes(query.toLowerCase())
          : true
      )
    : [];

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    setQuery(e.target.value);
    setSearching(true);
    setOpen(true);
    setActiveIndex(-1);
  }

  function handleSelect(ledger: Ledger) {
    setQuery(formatLedgerLabel(ledger));
    setOpen(false);
    setActiveIndex(-1);
    setSearching(false);
    onChange(String(ledger.id));
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setOpen(true);
        setActiveIndex(0);
        e.preventDefault();
      }
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0 && suggestions[activeIndex]) {
        handleSelect(suggestions[activeIndex]);
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
      setActiveIndex(-1);
      setSearching(false);
      const l = ledgers.find((ledger) => String(ledger.id) === value);
      if (l) setQuery(formatLedgerLabel(l));
    }
  }

  // Scroll active item into view
  useEffect(() => {
    if (activeIndex >= 0 && listRef.current) {
      const item = listRef.current.children[activeIndex] as HTMLElement | undefined;
      item?.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  // Close on outside click
  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearching(false);
        const l = ledgers.find((ledger) => String(ledger.id) === value);
        if (l) setQuery(formatLedgerLabel(l));
      }
    }
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, [value, ledgers]);

  const listboxId = `${id}-listbox`;

  return (
    <div ref={containerRef} className="combobox" style={{ position: 'relative' }}>
      <input
        ref={inputRef}
        id={id}
        className="input"
        type="text"
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-activedescendant={activeIndex >= 0 ? `${id}-option-${activeIndex}` : undefined}
        value={query}
        onChange={handleInputChange}
        onFocus={() => { setOpen(true); setSearching(false); inputRef.current?.select(); }}
        onKeyDown={handleKeyDown}
        placeholder={ledgers.length === 0 ? 'No ledgers available' : 'Search by name or GST…'}
        required={required}
        disabled={disabled || ledgers.length === 0}
      />
      {open && suggestions.length > 0 && (
        <ul
          ref={listRef}
          id={listboxId}
          role="listbox"
          className="combobox__list"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 50,
            maxHeight: '200px',
            overflowY: 'auto',
            margin: 0,
            padding: 0,
            listStyle: 'none',
            border: '1px solid var(--border, #d1d5db)',
            borderRadius: '6px',
            background: 'var(--surface, #fff)',
            boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
          }}
        >
          {suggestions.map((l, i) => (
            <li
              key={l.id}
              id={`${id}-option-${i}`}
              role="option"
              aria-selected={String(l.id) === value}
              onMouseDown={(e) => { e.preventDefault(); handleSelect(l); }}
              style={{
                padding: '8px 12px',
                cursor: 'pointer',
                background: i === activeIndex ? 'var(--accent, #3b82f6)' : String(l.id) === value ? 'var(--surface-subtle, #f3f4f6)' : 'transparent',
                color: i === activeIndex ? '#fff' : '#111827',
              }}
            >
              {l.name}
              {l.gst ? (
                <span style={{ opacity: 0.75, fontSize: '0.85em', color: i === activeIndex ? '#fff' : '#374151' }}> ({l.gst})</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {open && suggestions.length === 0 && searching && query.trim() !== '' && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 50,
            padding: '8px 12px',
            border: '1px solid var(--border, #d1d5db)',
            borderRadius: '6px',
            background: 'var(--surface, #fff)',
            color: 'var(--text-muted, #6b7280)',
            fontSize: '0.9em',
          }}
        >
          No ledgers matching "{query}"
        </div>
      )}
    </div>
  );
}
