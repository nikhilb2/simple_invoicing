import { useEffect, useRef, useState } from 'react';
import type { Product } from '../types/api';

type ProductComboboxProps = {
  id: string;
  products: Product[];
  value: string; // product id as string
  onChange: (productId: string, product: Product) => void;
  required?: boolean;
};

export default function ProductCombobox({ id, products, value, onChange, required }: ProductComboboxProps) {
  const selectedProduct = products.find((p) => String(p.id) === value);
  const [query, setQuery] = useState(selectedProduct ? `${selectedProduct.name} (${selectedProduct.sku})` : '');
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searching, setSearching] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Sync label when external value changes (e.g. default product on load)
  useEffect(() => {
    const p = products.find((prod) => String(prod.id) === value);
    if (p) setQuery(`${p.name} (${p.sku})`);
  }, [value, products]);

  const suggestions = open
    ? products.filter((p) =>
        searching && query.trim() !== ''
          ? `${p.name} ${p.sku}`.toLowerCase().includes(query.toLowerCase())
          : true
      )
    : [];

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    setQuery(e.target.value);
    setSearching(true);
    setOpen(true);
    setActiveIndex(-1);
  }

  function handleSelect(product: Product) {
    setQuery(`${product.name} (${product.sku})`);
    setOpen(false);
    setActiveIndex(-1);
    setSearching(false);
    onChange(String(product.id), product);
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
      const p = products.find((prod) => String(prod.id) === value);
      if (p) setQuery(`${p.name} (${p.sku})`);
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
        const p = products.find((prod) => String(prod.id) === value);
        if (p) setQuery(`${p.name} (${p.sku})`);
      }
    }
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, [value, products]);

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
        placeholder={products.length === 0 ? 'No products available' : 'Search by name or SKU…'}
        required={required}
        disabled={products.length === 0}
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
          {suggestions.map((p, i) => (
            <li
              key={p.id}
              id={`${id}-option-${i}`}
              role="option"
              aria-selected={String(p.id) === value}
              onMouseDown={(e) => { e.preventDefault(); handleSelect(p); }}
              style={{
                padding: '8px 12px',
                cursor: 'pointer',
                background: i === activeIndex ? 'var(--accent, #3b82f6)' : String(p.id) === value ? 'var(--surface-subtle, #f3f4f6)' : 'transparent',
                color: i === activeIndex ? '#fff' : '#111827',
              }}
            >
              {p.name} <span style={{ opacity: 0.75, fontSize: '0.85em', color: i === activeIndex ? '#fff' : '#374151' }}>({p.sku})</span>
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
          No products matching "{query}"
        </div>
      )}
    </div>
  );
}
