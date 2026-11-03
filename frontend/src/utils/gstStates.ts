/** GST state codes, as they appear at the start of a GSTIN. */
export const GST_STATES: { code: string; name: string }[] = [
  { code: '37', name: 'Andhra Pradesh' },
  { code: '28', name: 'Andhra Pradesh (before division)' },
  { code: '12', name: 'Arunachal Pradesh' },
  { code: '18', name: 'Assam' },
  { code: '10', name: 'Bihar' },
  { code: '04', name: 'Chandigarh' },
  { code: '22', name: 'Chhattisgarh' },
  { code: '26', name: 'Dadra and Nagar Haveli and Daman and Diu' },
  { code: '25', name: 'Daman and Diu' },
  { code: '07', name: 'Delhi' },
  { code: '30', name: 'Goa' },
  { code: '24', name: 'Gujarat' },
  { code: '06', name: 'Haryana' },
  { code: '02', name: 'Himachal Pradesh' },
  { code: '01', name: 'Jammu and Kashmir' },
  { code: '20', name: 'Jharkhand' },
  { code: '29', name: 'Karnataka' },
  { code: '32', name: 'Kerala' },
  { code: '38', name: 'Ladakh' },
  { code: '31', name: 'Lakshadweep' },
  { code: '23', name: 'Madhya Pradesh' },
  { code: '27', name: 'Maharashtra' },
  { code: '14', name: 'Manipur' },
  { code: '17', name: 'Meghalaya' },
  { code: '15', name: 'Mizoram' },
  { code: '13', name: 'Nagaland' },
  { code: '21', name: 'Odisha' },
  { code: '34', name: 'Puducherry' },
  { code: '03', name: 'Punjab' },
  { code: '08', name: 'Rajasthan' },
  { code: '11', name: 'Sikkim' },
  { code: '33', name: 'Tamil Nadu' },
  { code: '36', name: 'Telangana' },
  { code: '16', name: 'Tripura' },
  { code: '09', name: 'Uttar Pradesh' },
  { code: '05', name: 'Uttarakhand' },
  { code: '19', name: 'West Bengal' },
  { code: '35', name: 'Andaman and Nicobar Islands' },
  { code: '97', name: 'Other Territory' },
];

const STATE_CODES = new Set(GST_STATES.map((state) => state.code));

/**
 * Codes that only old data should carry. 28 is Andhra Pradesh before its 2014
 * division, now 37, and 25 is Daman and Diu, merged into 26 in 2020. Offered to
 * a seller in 37, 28 looks like home but is another state, so it charges IGST
 * on a local sale.
 */
const RETIRED_STATE_CODES = new Set(['25', '28']);

/** The states to offer, plus a retired one when that is what the document already says. */
export function placeOfSupplyOptions(current: string): { code: string; name: string }[] {
  return GST_STATES.filter((state) => !RETIRED_STATE_CODES.has(state.code) || state.code === current);
}

function stateCode(gstin?: string | null): string {
  const state = gstin?.trim().slice(0, 2) ?? '';
  return /^\d{2}$/.test(state) ? state : '';
}

/**
 * A place of supply the user picked. It belongs to the ledger it was picked for,
 * so choosing another ledger falls back to that ledger's own default.
 */
export type PlaceOfSupplyChoice = { ledgerId: string; code: string };

/**
 * The place of supply a sale will be filed under: the user's choice, else the
 * buyer's GSTIN state, else the seller's own state. Mirrors
 * default_place_of_supply on the backend. Empty when the seller has no GSTIN, or
 * when the buyer's GSTIN starts with a code that is not a state (99).
 */
export function resolvePlaceOfSupply(
  choice: PlaceOfSupplyChoice | null,
  ledgerId: string,
  companyGst?: string | null,
  ledgerGst?: string | null,
): string {
  if (!stateCode(companyGst)) return '';
  if (choice && choice.ledgerId === ledgerId) return choice.code;
  const buyerState = stateCode(ledgerGst);
  if (buyerState) return STATE_CODES.has(buyerState) ? buyerState : '';
  return stateCode(companyGst);
}

export function isInterstatePlaceOfSupply(placeOfSupply: string, companyGst?: string | null): boolean {
  const companyState = stateCode(companyGst);
  return Boolean(placeOfSupply && companyState) && placeOfSupply !== companyState;
}

/**
 * A warning when the place of supply an invoice was saved with no longer matches
 * the state on its buyer's GSTIN. It stays as saved, because a registered buyer can
 * take delivery elsewhere, and its tax was charged for that state.
 */
export function stalePlaceOfSupplyWarning(
  saved: string | null | undefined,
  current: string,
  ledgerGst?: string | null,
): string | null {
  const buyerState = stateCode(ledgerGst);
  if (!saved || current !== saved || !STATE_CODES.has(buyerState) || buyerState === saved) return null;
  const name = (code: string) => GST_STATES.find((state) => state.code === code)?.name ?? code;
  return (
    `This invoice was saved with ${saved} – ${name(saved)} as its place of supply, but the buyer's GSTIN `
    + `is now in ${buyerState} – ${name(buyerState)}. It won't change on its own, so check it before saving.`
  );
}
