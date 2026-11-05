import { AxiosError, type AxiosResponse } from 'axios';
import { describe, expect, test } from 'vitest';
import { missingQuantity, readStockShortage } from './stockShortage';

function failure(status: number, data: unknown) {
  return new AxiosError('failed', 'ERR_BAD_REQUEST', undefined, undefined, { status, data } as AxiosResponse);
}

describe('readStockShortage', () => {
  test('reads the product and the numbers from an insufficient-stock response', () => {
    const shortage = readStockShortage(
      failure(400, {
        detail: 'Insufficient inventory for Cordless Drill 500W',
        code: 'insufficient_stock',
        product_id: 7,
        product_name: 'Cordless Drill 500W',
        available: '0',
        required: '3',
      }),
    );
    expect(shortage).toEqual({ productId: 7, productName: 'Cordless Drill 500W', available: 0, required: 3 });
    expect(missingQuantity(shortage!)).toBe(3);
  });

  test('ignores every other failure, including a plain 400', () => {
    expect(readStockShortage(failure(400, { detail: 'Invoice date is outside the financial year' }))).toBeNull();
    expect(readStockShortage(failure(500, { code: 'insufficient_stock' }))).toBeNull();
    expect(readStockShortage(new Error('network'))).toBeNull();
  });

  test('asks for only what is missing when some stock is on hand', () => {
    expect(missingQuantity({ productId: 1, productName: 'x', available: 2, required: 5 })).toBe(3);
  });
});
