import { describe, expect, test } from 'vitest';
import { guideFor, pickTarget, tourOffer, type ComposerFacts, type FieldState, type Guide } from './tourSteps';

const EMPTY: ComposerFacts = {
  ledgerCount: 0,
  productCount: 0,
  ledgerChosen: false,
  productChosen: false,
  isSales: true,
  stockShortage: false,
  ledgerFormOpen: false,
  productFormOpen: false,
  stockFormOpen: false,
};
const READY: ComposerFacts = { ...EMPTY, ledgerCount: 1, productCount: 1, ledgerChosen: true, productChosen: true };

const id = (facts: Partial<ComposerFacts>, base = EMPTY) => guideFor({ ...base, ...facts }).id;

describe('guideFor follows what exists, not a saved position', () => {
  test('before the page has loaded', () => {
    expect(guideFor(null).id).toBe('loading');
  });

  test('walks customer, product, choosing, then creating', () => {
    expect(id({})).toBe('customer');
    expect(id({ ledgerCount: 1 })).toBe('product');
    expect(id({ ledgerCount: 1, productCount: 1 })).toBe('pick-customer');
    expect(id({ ledgerCount: 1, productCount: 1, ledgerChosen: true })).toBe('pick-product');
    expect(id({}, READY)).toBe('create');
  });

  test('skips what the company already has', () => {
    expect(id({ ledgerCount: 3, productCount: 2, ledgerChosen: true })).toBe('pick-product');
  });

  test('an open form comes first', () => {
    expect(id({ ledgerFormOpen: true })).toBe('customer-form');
    expect(id({ productFormOpen: true })).toBe('product-form');
    expect(id({ stockFormOpen: true }, READY)).toBe('stock-form');
  });

  test('a stock shortage is dealt with before anything else on the page', () => {
    expect(id({ stockShortage: true }, READY)).toBe('stock-shortage');
    expect(id({ stockShortage: true, stockFormOpen: true }, READY)).toBe('stock-form');
  });

  test('another voucher type is brought back to sales', () => {
    expect(id({ isSales: false }, READY)).toBe('voucher');
  });
});

describe('pickTarget', () => {
  const guide: Guide = {
    id: 'form',
    step: 1,
    title: '',
    body: '',
    fields: [
      { selector: '#name', title: 'name', body: '' },
      { selector: '#stock', title: 'stock', body: '', positive: true },
    ],
    action: { selector: '#save', title: 'save', body: '' },
  };
  const blank: FieldState = { visible: true, value: '', focused: false };
  const read = (fields: Record<string, Partial<FieldState>>) => (selector: string): FieldState => ({
    ...blank,
    ...fields[selector],
  });

  test('starts at the first empty field', () => {
    expect(pickTarget(guide, read({}))?.title).toBe('name');
  });

  test('stays on a field while it is being typed in', () => {
    expect(pickTarget(guide, read({ '#name': { value: 'A', focused: true } }))?.title).toBe('name');
  });

  test('moves on once the field is filled and left', () => {
    expect(pickTarget(guide, read({ '#name': { value: 'Asha' } }))?.title).toBe('stock');
  });

  test('zero does not count for a field that needs a positive number', () => {
    expect(pickTarget(guide, read({ '#name': { value: 'Asha' }, '#stock': { value: '0' } }))?.title).toBe('stock');
    expect(pickTarget(guide, read({ '#name': { value: 'Asha' }, '#stock': { value: '5' } }))?.title).toBe('save');
  });

  test('a field that is not on screen is passed over', () => {
    expect(
      pickTarget(guide, read({ '#name': { value: 'Asha' }, '#stock': { visible: false } }))?.title,
    ).toBe('save');
  });

  test('nothing to point at when the action is not on screen either', () => {
    const hidden = { visible: false };
    expect(pickTarget(guide, read({ '#name': hidden, '#stock': hidden, '#save': hidden }))).toBeNull();
  });
});

describe('tourOffer', () => {
  const none = { sales: { sales_invoice_count: 0, purchase_invoice_count: 0 } } as Parameters<typeof tourOffer>[2];
  const some = { sales: { sales_invoice_count: 2, purchase_invoice_count: 0 } } as Parameters<typeof tourOffer>[2];

  test('offered to an owner of a company with no invoices', () => {
    expect(tourOffer(null, 'admin', none)).toBe('offer');
    expect(tourOffer(null, 'manager', none)).toBe('offer');
  });

  test.each(['completed', 'skipped', 'not_needed'] as const)('never again after %s', (status) => {
    expect(tourOffer(status, 'admin', none)).toBe('none');
  });

  test('marked not needed once the company has invoices, whatever the role', () => {
    expect(tourOffer(null, 'admin', some)).toBe('not_needed');
    expect(tourOffer(null, 'staff', some)).toBe('not_needed');
  });

  test('not offered to staff, and nothing is saved for them', () => {
    expect(tourOffer(null, 'staff', none)).toBe('none');
  });

  test('decides nothing until the account and figures have loaded', () => {
    expect(tourOffer(undefined, 'admin', none)).toBe('none');
    expect(tourOffer(null, 'admin', null)).toBe('none');
  });
});
