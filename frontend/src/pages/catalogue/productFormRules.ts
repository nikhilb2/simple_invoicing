/**
 * Rules the product form applies before anything is sent, kept apart from the
 * component so they can be tested without a DOM.
 */

/**
 * The GST rates a product is normally sold at, 40 being the rate that came in with
 * GST 2.0. The form still takes any other rate under "Other rate", because older
 * products and special goods carry rates such as 0.25 or 3.
 */
export const GST_SLABS = [0, 5, 12, 18, 28, 40] as const;

export function isGstSlab(rate: string): boolean {
  return rate.trim() !== '' && GST_SLABS.some((slab) => slab === Number(rate));
}

export const GST_ZERO_NOTE =
  'You are charging no GST on this product. Choose 0% only for items that are exempt or nil-rated; otherwise pick the rate that applies.';

const HSN_PATTERN = /^(?:\d{4}|\d{6}|\d{8})$/;

export const HSN_ERROR = 'HSN/SAC code must be 4, 6 or 8 digits, numbers only. Leave it blank if you do not know it yet.';

/** What is wrong with an HSN/SAC code, in the owner's words, or '' when it is fine or blank. */
export function hsnProblem(value: string): string {
  const code = value.trim();
  return code === '' || HSN_PATTERN.test(code) ? '' : HSN_ERROR;
}

/** The HSN complaint is about the field being typed in, so editing it withdraws the complaint; other errors stay. */
export function errorAfterHsnEdit(error: string): string {
  return error === HSN_ERROR ? '' : error;
}

/**
 * The server names a failing field by its column ("Hsn sac: HSN/SAC must be 4, 6
 * or 8 digits"). This form says it in its own words instead.
 */
export function plainProductError(message: string): string {
  return /^hsn[ _]sac\b/i.test(message) && /4, 6 or 8 digits/.test(message) ? HSN_ERROR : message;
}

/** True when a new product will track stock yet start with none, which makes its first sale fail. */
export function startsWithNoStock(tracksStock: boolean, openingQuantity: number): boolean {
  return tracksStock && openingQuantity === 0;
}

export const NO_STOCK_WARNING =
  'You are tracking stock for this item but starting with 0, so you will not be able to sell it until you add stock. Enter how many you have now, or stop tracking stock if you do not count this item.';

export const NO_STOCK_SAVED_NOTE =
  'It has 0 in stock, so add stock before you sell it (Update stock on the invoice screen, or the catalogue).';
