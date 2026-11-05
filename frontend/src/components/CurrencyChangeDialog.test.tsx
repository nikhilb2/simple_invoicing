import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import CurrencyChangeDialog from './CurrencyChangeDialog';
import { isCurrencyChange } from '../utils/currencyChange';

describe('CurrencyChangeDialog', () => {
  it('says existing invoices keep the old currency and only new ones use the new one', () => {
    const html = renderToStaticMarkup(
      <CurrencyChangeDialog fromCurrency="USD" toCurrency="INR" onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(html).toContain('role="dialog"');
    expect(html).toContain('Invoices you have already created will stay in USD');
    expect(html).toContain('Only new invoices will use INR');
    expect(html).toContain('Change to INR');
  });
});

describe('isCurrencyChange', () => {
  it('is true only when a saved currency is replaced by a different one', () => {
    expect(isCurrencyChange('USD', 'INR')).toBe(true);
    expect(isCurrencyChange('usd ', 'USD')).toBe(false);
    expect(isCurrencyChange('INR', 'INR')).toBe(false);
  });

  it('is false when nothing was saved yet, since no invoice can exist', () => {
    expect(isCurrencyChange('', 'INR')).toBe(false);
  });
});
