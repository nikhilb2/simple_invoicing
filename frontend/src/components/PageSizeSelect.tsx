/** Rows per page options for paginated lists. */

/**
 * The only sizes a list page may offer. Both the ledgers and invoices list
 * endpoints cap page_size at 500, so every option here stays under the
 * backend maximum.
 */
export const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;

export const DEFAULT_PAGE_SIZE = 20;

/**
 * Read a previously chosen page size. Anything missing, unparseable, or
 * outside the offered options falls back, and a storage failure (private
 * mode, disabled cookies) never breaks the page: it just gets the default.
 */
export function readStoredPageSize(key: string, fallback: number = DEFAULT_PAGE_SIZE): number {
  try {
    const raw = globalThis.localStorage?.getItem(key);
    if (raw === null || raw === undefined) return fallback;
    const parsed = Number(raw);
    return (PAGE_SIZE_OPTIONS as readonly number[]).includes(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

/** Persist a page size choice. A storage failure is swallowed on purpose. */
export function storePageSize(key: string, pageSize: number): void {
  try {
    globalThis.localStorage?.setItem(key, String(pageSize));
  } catch {
    /* the page works without storage; the choice just does not persist */
  }
}

type PageSizeSelectProps = {
  id: string;
  value: number;
  onChange: (pageSize: number) => void;
};

/**
 * Small "Rows per page" select, meant to sit next to a list's pagination
 * controls. The caller owns the state and resets to page 1 on change.
 */
export default function PageSizeSelect({ id, value, onChange }: PageSizeSelectProps) {
  return (
    <label htmlFor={id} className="ledger-pagination__status">
      Rows per page{' '}
      <select
        id={id}
        className="select"
        style={{ width: 'auto' }}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {PAGE_SIZE_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}
