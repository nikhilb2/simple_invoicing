import { ChevronLeft, ChevronRight } from 'lucide-react';

/**
 * The one pager for every paginated list.
 *
 * Products, Inventory and Products & Inventory each hand-rolled this with
 * inline styles, and LedgersPage grew a nicer variant in `.ledger-pagination`.
 * This is that variant, shared.
 *
 * Unlike the versions it replaces, it renders even at a single page: hiding it
 * also hid the row count, so a list that fit on one page never told you how
 * much was in it.
 */

type PaginationProps = {
  page: number;
  totalPages: number;
  /** Total rows across all pages, for the "showing X–Y of N" line. */
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  /** Plural noun for the row count, e.g. "products". */
  itemLabel?: string;
};

export default function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  itemLabel = 'items',
}: PaginationProps) {
  if (total === 0) return null;

  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  return (
    <div className="ledger-pagination">
      <button
        type="button"
        className="button button--ghost button--small"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        aria-label="Previous page"
      >
        <ChevronLeft size={15} aria-hidden="true" />
        Previous
      </button>
      {/* Polite: paging is user-initiated, so the count should not interrupt. */}
      <span className="ledger-pagination__status" aria-live="polite">
        <strong>
          {first}–{last}
        </strong>{' '}
        of {total} {itemLabel}
      </span>
      <button
        type="button"
        className="button button--ghost button--small"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
        aria-label="Next page"
      >
        Next
        <ChevronRight size={15} aria-hidden="true" />
      </button>
    </div>
  );
}
