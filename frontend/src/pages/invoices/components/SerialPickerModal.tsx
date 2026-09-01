import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Check } from 'lucide-react';
import ModalCloseButton from '../../../components/ModalCloseButton';
import { getApiErrorMessage } from '../../../api/client';
import { fetchAvailableSerials } from '../../../features/serials/api';
import { serialQueryKeys } from '../../../features/serials/queryKeys';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { formatInvoiceDateLabel } from '../../../utils/invoiceDueDate.ts';

type SerialPickerModalProps = {
  productId: number;
  productName: string;
  /** Serials already on the line; they open selected and can be unselected. */
  selected: string[];
  onCancel: () => void;
  onConfirm: (serials: string[]) => void;
};

export default function SerialPickerModal({
  productId,
  productName,
  selected,
  onCancel,
  onConfirm,
}: SerialPickerModalProps) {
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<string[]>(selected);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [oldestCount, setOldestCount] = useState('5');
  const listRef = useRef<HTMLUListElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEscapeClose(onCancel);

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => { setDebouncedSearch(search.trim()); setPage(1); }, 250);
    return () => clearTimeout(timer);
  }, [search]);

  const serialsQuery = useQuery({
    queryKey: serialQueryKeys.available(productId, debouncedSearch, page),
    queryFn: () => fetchAvailableSerials({ productId, search: debouncedSearch, page }),
  });

  const rows = serialsQuery.data?.items ?? [];

  // Same as ProductCombobox: the active row follows the keyboard, not the mouse.
  useEffect(() => {
    if (activeIndex < 0 || !listRef.current) return;
    const row = listRef.current.children[activeIndex] as HTMLElement | undefined;
    row?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  function toggle(serialNumber: string) {
    setPicked((current) =>
      current.includes(serialNumber)
        ? current.filter((entry) => entry !== serialNumber)
        : [...current, serialNumber],
    );
  }

  function selectOldest() {
    const count = Number(oldestCount);
    if (!Number.isFinite(count) || count <= 0) return;
    // The list arrives oldest-first, so the first N rows are the FIFO pick.
    const oldest = rows.slice(0, count).map((serial) => serial.serial_number);
    setPicked((current) => [...current, ...oldest.filter((entry) => !current.includes(entry))]);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, rows.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (activeIndex >= 0 && rows[activeIndex]) {
        toggle(rows[activeIndex].serial_number);
      } else {
        onConfirm(picked);
      }
    }
  }

  const listboxId = 'serial-picker-listbox';

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="serial-picker-title">
      <div className="modal-panel" onKeyDown={handleKeyDown}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">In stock</p>
            <h2 id="serial-picker-title" className="nav-panel__title">Pick serials — {productName}</h2>
          </div>
          <div className="button-row">
            <div className="status-chip">{picked.length} selected</div>
            <ModalCloseButton onClick={onCancel} label="Close serial picker" />
          </div>
        </div>

        <div className="stack">
          <div className="field">
            <label htmlFor="serial-picker-search">Search serials</label>
            <input
              id="serial-picker-search"
              ref={searchRef}
              className="input"
              type="text"
              autoComplete="off"
              role="combobox"
              aria-expanded
              aria-controls={listboxId}
              aria-activedescendant={activeIndex >= 0 ? `serial-picker-option-${activeIndex}` : undefined}
              value={search}
              onChange={(event) => { setSearch(event.target.value); setActiveIndex(-1); }}
              placeholder="Last digits of an IMEI…"
            />
          </div>

          <div className="serial-picker__quick">
            <label className="serial-picker__quick-label" htmlFor="serial-picker-oldest">Select oldest</label>
            <input
              id="serial-picker-oldest"
              className="input serial-picker__quick-input"
              type="number"
              min="1"
              step="1"
              value={oldestCount}
              onChange={(event) => setOldestCount(event.target.value)}
            />
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={selectOldest}
              disabled={rows.length === 0}
            >
              Select oldest {oldestCount || ''}
            </button>
          </div>

          {serialsQuery.isLoading ? <p className="muted-text">Loading serials…</p> : null}
          {serialsQuery.error ? (
            <p className="field-warning">{getApiErrorMessage(serialsQuery.error, 'Unable to load serials')}</p>
          ) : null}
          {!serialsQuery.isLoading && rows.length === 0 ? (
            <p className="empty-state">No in-stock serials for this product.</p>
          ) : null}

          <ul id={listboxId} ref={listRef} className="serial-picker__list" role="listbox" aria-multiselectable="true">
            {rows.map((serial, index) => {
              const isPicked = picked.includes(serial.serial_number);
              return (
                <li
                  key={serial.id}
                  id={`serial-picker-option-${index}`}
                  role="option"
                  aria-selected={isPicked}
                  className={`serial-picker__row${index === activeIndex ? ' is-active' : ''}${isPicked ? ' is-picked' : ''}`}
                  onMouseDown={(event) => { event.preventDefault(); toggle(serial.serial_number); setActiveIndex(index); }}
                >
                  <span className="serial-picker__check" aria-hidden="true">
                    {isPicked ? <Check size={13} /> : null}
                  </span>
                  <span className="serial-picker__number">{serial.serial_number}</span>
                  <span className="serial-picker__meta">
                    {serial.purchase_invoice
                      ? `${serial.purchase_invoice.invoice_number ?? `#${serial.purchase_invoice.id}`} · ${formatInvoiceDateLabel(serial.purchase_invoice.invoice_date)}`
                      : `Added ${formatInvoiceDateLabel(serial.created_at)}`}
                  </span>
                </li>
              );
            })}
          </ul>

          {(serialsQuery.data?.total_pages ?? 1) > 1 ? (
            <div className="serial-picker__pages">
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={page <= 1}
                onClick={() => { setPage((current) => current - 1); setActiveIndex(-1); }}
              >
                Previous
              </button>
              <span className="muted-text">Page {page} of {serialsQuery.data?.total_pages}</span>
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={page >= (serialsQuery.data?.total_pages ?? 1)}
                onClick={() => { setPage((current) => current + 1); setActiveIndex(-1); }}
              >
                Next
              </button>
            </div>
          ) : null}

          <div className="button-row">
            <button type="button" className="button button--ghost" onClick={onCancel}>Cancel</button>
            <button type="button" className="button button--primary" onClick={() => onConfirm(picked)}>
              Use {picked.length} serial{picked.length === 1 ? '' : 's'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
