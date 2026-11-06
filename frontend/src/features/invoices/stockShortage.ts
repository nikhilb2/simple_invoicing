import axios from 'axios';

/** What the API says when a sale needs more of a product than the shop holds. */
export type StockShortage = {
  productId: number;
  productName: string;
  available: number;
  required: number;
};

/** The shortage in a failed save, or null when the failure was something else. */
export function readStockShortage(error: unknown): StockShortage | null {
  if (!axios.isAxiosError(error)) return null;
  const body = error.response?.data as Record<string, unknown> | undefined;
  if (error.response?.status !== 400 || body?.code !== 'insufficient_stock') return null;
  const productId = Number(body.product_id);
  const available = Number(body.available);
  const required = Number(body.required);
  if (!Number.isFinite(productId) || !Number.isFinite(available) || !Number.isFinite(required)) return null;
  return {
    productId,
    productName: typeof body.product_name === 'string' ? body.product_name : 'this product',
    available,
    required,
  };
}

/** How many more units would let the sale go through. */
export function missingQuantity(shortage: StockShortage): number {
  return Math.max(shortage.required - shortage.available, 0);
}
