/** Match the dashboard's out-of-stock and low-stock metrics. */
export function needsStockAttention(quantity: number, reorderLevel = 0): boolean {
  return quantity <= 0 || (reorderLevel > 0 && quantity <= reorderLevel);
}
