export type PaymentInvoiceAllocationLike = {
  invoice_id: number;
  invoice_number?: string | null;
  allocated_amount: number | string | null | undefined;
};

export function validateAllocations(
  allocations: PaymentInvoiceAllocationLike[] | undefined,
  paymentAmount: number,
): string | null {
  const list = allocations ?? [];
  for (const allocation of list) {
    const amount = Number(allocation.allocated_amount);
    if (!Number.isFinite(amount) || amount <= 0) {
      return `Allocated amount for ${allocation.invoice_number ?? `invoice ${allocation.invoice_id}`} must be greater than 0`;
    }
  }
  const totalPaise = list.reduce((sum, a) => sum + Math.round(Number(a.allocated_amount || 0) * 100), 0);
  if (totalPaise > Math.round(paymentAmount * 100)) {
    return 'Allocated amounts exceed the payment amount';
  }
  return null;
}
