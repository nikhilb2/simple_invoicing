# Invoice Due Logic

## Overview

Invoice due dates are optional.

- If the user does not select a due date option, `due_date` is stored as `null`.
- If the user selects an exact date, that value is sent directly.
- If the user selects a relative number of days, the due date is computed from the invoice date, not from the current date.

## Frontend Behavior

Shared due-date helpers live in `frontend/src/utils/invoiceDueDate.ts`.

- `none`: no due date
- `exact`: user-selected calendar date
- `days`: invoice date plus N days

The invoice create flows on the main invoice page and quick-create modal both use the same helper so they resolve due dates consistently.

## Backend Behavior

The backend already stores `invoices.due_date` as a nullable field.

Invoice responses now also expose derived collection fields:

- `paid_amount`
- `remaining_amount`
- `outstanding_amount`
- `payment_status`
- `due_in_days`

These are calculated from active invoice totals, credit notes, and payment allocations.

## Payment Allocation Rules

Receipt and payment entries can be allocated against invoices through `payment_invoice_allocations`.

- Fully paid invoices are excluded from selection.
- Partial allocations are allowed.
- Oldest invoices can be auto-selected through backend suggestions.
- Editing an existing payment reloads outstanding invoices while excluding the current payment from the outstanding calculation.

## Dues Page Filters

The dues page is available at `/invoice-dues`.

Supported filters:

- overdue invoices
- next 7 days
- next 15 days
- custom number of days ahead
- exact due date
- all due invoices

The dues page is backed by `GET /invoices/dues`.

## Notes

- Relative due dates are anchored to invoice date because that was the explicit product decision.
- The dues page includes overdue invoices as a first-class filter.
- Payment status is derived, not stored separately.