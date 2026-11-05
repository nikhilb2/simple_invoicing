import type { DashboardMetrics, UserProfile } from '../../types/api';
import { hasPostedInvoices } from '../../utils/getStarted';

export type FirstInvoiceTourStatus = 'completed' | 'skipped' | 'not_needed';

/** What the invoice page knows right now. The walkthrough follows this, so it never asks for something already done. */
export type ComposerFacts = {
  ledgerCount: number;
  productCount: number;
  ledgerChosen: boolean;
  productChosen: boolean;
  isSales: boolean;
  stockShortage: boolean;
  ledgerFormOpen: boolean;
  productFormOpen: boolean;
  stockFormOpen: boolean;
};

export type GuideTarget = {
  selector: string;
  title: string;
  body: string;
  /** A field that is only done once it holds a number above zero, such as opening stock. */
  positive?: boolean;
};

export type Guide = {
  id: string;
  /** 1 to TOUR_STEPS, for the progress marker. */
  step: number;
  title: string;
  body: string;
  /** Form fields, in order. The first unfinished one is highlighted. */
  fields?: GuideTarget[];
  /** Highlighted when no field is left to fill in. */
  action?: GuideTarget;
};

export const TOUR_STEPS = 4;
export const INVOICE_PATH = '/invoices';

const tour = (name: string) => `[data-tour="${name}"]`;

const CUSTOMER: Guide = {
  id: 'customer',
  step: 1,
  title: 'Add your customer',
  body: 'Everything you create here is real, so use a real customer if you can.',
  action: {
    selector: tour('add-customer'),
    title: 'Add your customer',
    body: 'Who is this invoice for? Click Add a customer. You stay on this page.',
  },
};

const CUSTOMER_FORM: Guide = {
  id: 'customer-form',
  step: 1,
  title: 'Fill in the customer',
  body: 'Only the name, phone number and address are needed.',
  fields: [
    {
      selector: '#modal-ledger-name',
      title: 'Customer name',
      body: 'As it should appear on the invoice.',
    },
    {
      selector: '#modal-ledger-phone',
      title: 'Phone number',
      body: 'The customer’s phone number.',
    },
    {
      selector: '#modal-ledger-address',
      title: 'Address',
      body: 'This prints on the invoice. Include the state if you can.',
    },
  ],
  action: {
    selector: tour('save-customer'),
    title: 'Save the customer',
    body: 'A ledger is this app’s name for a customer’s account. Leave the other fields blank. Only enter an opening balance if they already owed you money before you started using this app, not for this sale.',
  },
};

const PRODUCT: Guide = {
  id: 'product',
  step: 2,
  title: 'Add what you sold',
  body: 'Add the product or service that goes on this invoice.',
  action: {
    selector: tour('add-product'),
    title: 'Add what you sold',
    body: 'Click Add a product. You stay on this page.',
  },
};

const PRODUCT_FORM: Guide = {
  id: 'product-form',
  step: 2,
  title: 'Fill in the product',
  body: 'Only a few of these fields are needed for now.',
  fields: [
    {
      selector: '#modal-product-name',
      title: 'Product name',
      body: 'As it should appear on the invoice.',
    },
    {
      selector: '#modal-product-sku',
      title: 'SKU',
      body: 'A short code of your own for this product, such as BAG-01.',
    },
    {
      selector: '#modal-product-price',
      title: 'Unit price',
      body: 'What you charge for one unit.',
    },
    {
      selector: '#modal-product-gst-rate',
      title: 'GST %',
      body: 'The GST rate on this product. Check it, because it goes on the invoice and your returns.',
    },
    {
      selector: '#modal-product-opening-stock',
      title: 'Opening stock',
      body: 'How many you have right now. An invoice can’t sell more than you have. For a service, untick Maintain inventory above instead.',
      positive: true,
    },
  ],
  action: {
    selector: tour('save-product'),
    title: 'Save the product',
    body: 'That’s all it needs. You can add the rest later.',
  },
};

const VOUCHER: Guide = {
  id: 'voucher',
  step: 3,
  title: 'Switch back to Sales',
  body: 'This walkthrough creates a sales invoice.',
  action: {
    selector: '#invoice-voucher-type',
    title: 'Switch back to Sales',
    body: 'This walkthrough creates a sales invoice, so choose Sales here.',
  },
};

const PICK_CUSTOMER: Guide = {
  id: 'pick-customer',
  step: 3,
  title: 'Choose the customer',
  body: 'Pick who this invoice is for.',
  action: {
    selector: '#invoice-ledger',
    title: 'Choose the customer',
    body: 'Click here and pick who this invoice is for.',
  },
};

const PICK_PRODUCT: Guide = {
  id: 'pick-product',
  step: 3,
  title: 'Choose what you sold',
  body: 'Pick the product for the first line of the invoice.',
  action: {
    selector: 'input[id^="invoice-product-"]',
    title: 'Choose what you sold',
    body: 'Click here and pick the product. Then check the quantity and price next to it.',
  },
};

const STOCK_SHORTAGE: Guide = {
  id: 'stock-shortage',
  step: 4,
  title: 'Add the missing stock',
  body: 'There isn’t enough of this product in stock for this invoice.',
  action: {
    selector: tour('add-stock'),
    title: 'Add the missing stock',
    body: 'There isn’t enough in stock for this invoice. Click here to add it. Your invoice stays as you filled it in.',
  },
};

const STOCK_FORM: Guide = {
  id: 'stock-form',
  step: 4,
  title: 'Save the stock',
  body: 'Check the quantity, then save.',
  action: {
    selector: tour('save-stock'),
    title: 'Save the stock',
    body: 'The quantity is filled in with what’s missing. Change it if you have more, then save. Your invoice is still there.',
  },
};

const CREATE: Guide = {
  id: 'create',
  step: 4,
  title: 'Create your invoice',
  body: 'Check the details, then create the invoice.',
  action: {
    selector: tour('create-invoice'),
    title: 'Create your invoice',
    body: 'Check the date, quantity and price. Click here when it looks right. This creates a real invoice and takes the quantity out of your stock.',
  },
};

export const LOADING_GUIDE: Guide = {
  id: 'loading',
  step: 1,
  title: 'Opening the invoice page',
  body: 'Just a moment.',
};

export const AWAY_GUIDE: Guide = {
  id: 'away',
  step: 1,
  title: 'Your invoice is waiting',
  body: 'You left the invoice page. Go back to carry on from where you stopped.',
};

/** The next thing to do, worked out from what exists rather than from a saved position. */
export function guideFor(facts: ComposerFacts | null): Guide {
  if (!facts) return LOADING_GUIDE;
  if (facts.ledgerFormOpen) return CUSTOMER_FORM;
  if (facts.productFormOpen) return PRODUCT_FORM;
  if (facts.stockFormOpen) return STOCK_FORM;
  if (!facts.isSales) return VOUCHER;
  if (facts.ledgerCount === 0) return CUSTOMER;
  if (facts.productCount === 0) return PRODUCT;
  if (facts.stockShortage) return STOCK_SHORTAGE;
  if (!facts.ledgerChosen) return PICK_CUSTOMER;
  if (!facts.productChosen) return PICK_PRODUCT;
  return CREATE;
}

export type FieldState = {
  /** The element exists and takes up space on screen. */
  visible: boolean;
  value: string;
  focused: boolean;
};

function fieldIsFinished(field: GuideTarget, state: FieldState): boolean {
  // Still being typed in: moving on now would pull the hint away mid-word.
  if (state.focused) return false;
  const value = state.value.trim();
  return field.positive ? Number(value) > 0 : value !== '';
}

/** Which part of the guide to point at: the first unfinished field, then the action. */
export function pickTarget(guide: Guide, readField: (selector: string) => FieldState): GuideTarget | null {
  for (const field of guide.fields ?? []) {
    const state = readField(field.selector);
    if (state.visible && !fieldIsFinished(field, state)) return field;
  }
  if (guide.action && readField(guide.action.selector).visible) return guide.action;
  return null;
}

export type TourOffer = 'offer' | 'not_needed' | 'none';

/**
 * Whether the dashboard should offer the walkthrough.
 *
 * `undefined` means /auth/me has not answered, so nothing is decided on it. Staff
 * cannot add products, so they are not offered a tour they could not finish, and
 * nothing is saved for them.
 */
export function tourOffer(
  status: FirstInvoiceTourStatus | null | undefined,
  companyRole: UserProfile['role'] | null,
  metrics: Pick<DashboardMetrics, 'sales'> | null,
): TourOffer {
  if (status !== null || !metrics) return 'none';
  if (hasPostedInvoices(metrics)) return 'not_needed';
  return companyRole === 'admin' || companyRole === 'manager' ? 'offer' : 'none';
}

export function canStartTour(companyRole: UserProfile['role'] | null): boolean {
  return companyRole === 'admin' || companyRole === 'manager';
}
