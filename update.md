# Update Log

## 2026-04-07
- Implemented keyboard shortcuts in the invoices flow.
- Added shortcut help UI in the invoice composer.
- Added navigation shortcut guidance in the app shell.
- Persisted the invoice line-item `tax_included` flag so edited invoices preserve the original entry mode.
- Added a migration for the new `invoice_items.tax_included` column.
- Updated frontend API types and invoice schemas to include `tax_included`.

## 2026-04-07 - Keyboard shortcuts follow-up
- Created branch `feature/keyboard-shortcuts`.
- Added global invoice composer shortcuts for submit, add line item, add ledger, add product, update stock, and open help.
- Added a keyboard-shortcut help modal and a visible hint in the layout.
