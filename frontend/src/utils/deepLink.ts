import { useEffect } from 'react';

/**
 * Query-param deep links, as the MCP `search` / `fetch` tools emit them.
 *
 * A ChatGPT citation only renders if its URL resolves to the actual record, and
 * this app has list pages rather than detail routes for invoices, credit notes,
 * products, serials and payments. So each of those pages honours one parameter
 * — /invoices-view?invoice_id=, /credit-notes?cn_id=,
 * /products-inventory?product_id=|serial=, /cash-bank?payment_id= — by moving
 * its own filters onto the record and flagging the row.
 *
 * A deep-linked id is user-supplied and may name a record that was deleted, or
 * belongs to another company: every caller treats a failed lookup as an error
 * message on an otherwise working page, never as a crash.
 */

/**
 * Plain digits only, and no leading zero.
 *
 * `Number()` would also accept '1e3', ' 12 ' and '0x1f', quietly turning a
 * malformed citation into a request for some *other* record. A record id in a
 * URL is only ever written one way.
 */
const RECORD_ID = /^[1-9][0-9]{0,15}$/;

/** A positive-integer record id from a query param, or null if it is neither. */
export function numericParam(params: URLSearchParams, key: string): number | null {
  const raw = params.get(key);
  if (raw === null || !RECORD_ID.test(raw)) return null;
  return Number(raw);
}

/**
 * Scrolls the flagged row into view once the list that contains it has
 * rendered. Deferred a frame because `ready` flips in the same commit that
 * paints the rows, so the element does not exist yet when the effect runs.
 */
export function useDeepLinkScroll(elementId: string | null, ready: boolean) {
  useEffect(() => {
    if (!elementId || !ready) return undefined;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(elementId)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [elementId, ready]);
}

/** The row class that flags a deep-linked record. See `.deep-link-target`. */
export function deepLinkClass(isTarget: boolean, base = ''): string {
  return isTarget ? `${base} deep-link-target`.trim() : base;
}
