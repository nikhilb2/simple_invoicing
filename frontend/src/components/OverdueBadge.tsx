import { Clock } from 'lucide-react';
import { isOverdueInvoice, overdueLabel, type OverdueInvoiceInput } from '../utils/invoiceDueDate.ts';

interface OverdueBadgeProps {
  invoice: OverdueInvoiceInput;
}

/**
 * Compact red badge for an overdue unpaid invoice. Renders nothing unless
 * the invoice is actually overdue, so call sites need no gating of their own.
 * The clock icon and the day count keep it distinct from the Cancelled badge.
 */
export default function OverdueBadge({ invoice }: OverdueBadgeProps) {
  if (!isOverdueInvoice(invoice)) {
    return null;
  }
  const label = overdueLabel(invoice.due_in_days);
  if (label === null) {
    return null;
  }
  return (
    <span className="overdue-badge">
      <Clock size={12} aria-hidden="true" />
      {label}
    </span>
  );
}
