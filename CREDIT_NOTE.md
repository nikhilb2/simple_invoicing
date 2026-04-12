# Credit Note Feature

## Overview

Credit notes allow adjusting previously issued invoices for returns, corrections, or discounts, with proportional GST reversal. A single credit note can cover **multiple invoices from the same ledger**.

Implementation is tracked under [Epic #259](https://github.com/nikhilb2/simple_invoicing/issues/259) across four phases.

---

## Architecture

### Primary Anchor: Ledger

A credit note anchors to a **ledger** (`credit_notes.ledger_id`), not a single invoice. Multiple invoices from the same ledger can be covered by one credit note via the `credit_note_invoice_refs` join table.

```
credit_notes
  └─ ledger_id      FK → buyers (primary anchor)
  └─ CreditNoteInvoiceRef[]  (join table)
       └─ invoice_id  FK → invoices
  └─ CreditNoteItem[]
       └─ invoice_id        FK → invoices (for per-invoice credit_status)
       └─ invoice_item_id   FK → invoice_items (for quantity validation)
```

### Schema

**`credit_notes`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | int PK | |
| `credit_note_number` | string unique | Generated via `credit_note` series |
| `ledger_id` | FK → buyers | Primary anchor |
| `financial_year_id` | FK → financial_years | |
| `created_by` | FK → users | |
| `credit_note_type` | `return\|discount\|adjustment` | Default `return` |
| `reason` | text nullable | |
| `status` | `active\|cancelled` | Default `active` |
| `taxable_amount`, `cgst_amount`, `sgst_amount`, `igst_amount`, `total_amount` | Decimal(10,2) | Aggregated from items |
| `created_at` | timestamp | |
| `cancelled_at` | timestamp nullable | |

**`credit_note_invoice_refs`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | int PK | |
| `credit_note_id` | FK → credit_notes | |
| `invoice_id` | FK → invoices | |
| — | unique `(credit_note_id, invoice_id)` | |

No `applied_amount` column — amounts are derived from item-level data.

**`credit_note_items`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | int PK | |
| `credit_note_id` | FK → credit_notes | |
| `invoice_id` | FK → invoices NOT NULL | Which invoice this item belongs to |
| `invoice_item_id` | FK → invoice_items NOT NULL | Required for both return and discount CNs |
| `product_id` | FK → products | Snapshot reference |
| `quantity` | numeric | |
| `unit_price`, `gst_rate` | Decimal | |
| `taxable_amount`, `tax_amount`, `line_total` | Decimal(10,2) | |
| `created_at` | timestamp | |

---

## Credit Status

`invoices.credit_status` values: `not_credited | partially_credited | fully_credited`

Computed per invoice by summing `line_total` of all **active** `credit_note_items` where `cn_item.invoice_id = invoice.id`, then comparing to `invoice.taxable_amount`.

Status is recomputed:
- After a credit note is **created** — for all referenced invoices
- After a credit note is **cancelled** — for all invoices that had items on the CN

---

## Credit Note Types

| Type | Description |
|------|-------------|
| `return` | Goods/services returned — quantity and amount credited |
| `discount` | Post-invoice discount — line items still anchored to `invoice_item_id`; discount expressed via reason + adjusted quantity/price |
| `adjustment` | Correction for any other reason |

Discount credit notes use the **same item-based structure** as return CNs (anchored to `invoice_item_id`). There is no separate free-form line type.

---

## API Endpoints

```
POST /api/credit-notes/           — Create credit note
GET  /api/credit-notes/           — List (paginated + filtered)
GET  /api/credit-notes/{id}       — Get detail
POST /api/credit-notes/{id}/cancel — Cancel
```

### List Filters

| Param | Type | Description |
|-------|------|-------------|
| `ledger_id` | int | Filter CNs by ledger |
| `invoice_id` | int | Filter via credit_note_invoice_refs join |
| `status` | string | `active` or `cancelled` |
| `search` | string | ilike on credit_note_number |
| `date_from`, `date_to` | date | CN creation date range |
| `page`, `page_size` | int | Pagination |

### Create Payload

```json
{
  "ledger_id": 42,
  "invoice_ids": [101, 102],
  "credit_note_type": "return",
  "reason": "Goods returned",
  "items": [
    {
      "invoice_id": 101,
      "invoice_item_id": 501,
      "quantity": 2
    },
    {
      "invoice_id": 102,
      "invoice_item_id": 610,
      "quantity": 1
    }
  ]
}
```

**Validation rules:**
- All `invoice_ids` must belong to `ledger_id` → 400 if mismatch
- Each item's `invoice_id` must be in `invoice_ids` → 400 if mismatch
- Sum of existing active CN items + new quantity ≤ original item quantity per `invoice_item_id`

---

## Frontend

### Pages & Routes

| Route | Page | Notes |
|-------|------|-------|
| `/credit-notes` | `CreditNotesPage.tsx` | Split: create form (left) + list (right) |
| `/credit-notes?ledger=<id>` | `CreditNotesPage.tsx` | Ledger pre-selected via `useSearchParams` |

Sidebar entry: **Credit Notes**, under Main group after Invoices.

### Create Form — Ledger-First Flow

1. **Ledger selector** — searchable dropdown; pre-populated from `?ledger=<id>` param
2. **Invoice multi-selector** — filtered by chosen ledger; shows invoice #, date, total, `credit_status`; only active invoices with `credit_status != fully_credited` are selectable
3. **Item selection** — grouped by invoice; shows original qty, already-credited qty, available qty; quantity-to-credit input with cumulative validation
4. **Summary & Submit** — taxable / CGST / SGST / IGST / total; `credit_note_type` selector; optional `reason`; submit disabled until at least one valid line is entered

### Ledger View Integration

`LedgerViewPage` has a **"Create Credit Note"** button → `navigate('/credit-notes?ledger=<id>')`. No inline CN list on the ledger page.

### Invoice Page Integration

- `credit_status` badge shown on invoice rows
- Per-invoice "Create Credit Note" action → `/credit-notes?invoice=<id>` (CN page auto-selects ledger + invoice)

---

## Numbering

Credit notes use a dedicated `credit_note` voucher type in `InvoiceSeries`, scoped to the active financial year. Series configuration (prefix, suffix, pad digits) mirrors the invoice series setup.

---

## Immutability & Cancellation

- Credit notes are **immutable** after creation — no edits allowed
- Cancellation sets `status = cancelled` and `cancelled_at = now()`
- On cancel, `credit_status` is recomputed for all invoices that had items on the CN

---

## Phase Tracking

| Phase | Issue | Status | Scope |
|-------|-------|--------|-------|
| 1 — DB | #260 | Implemented | Migrations: `credit_notes`, `credit_note_invoice_refs`, `credit_note_items`, `credit_status` column |
| 2 — Backend | #262 | Implemented | Models, schemas, service, API routes, numbering, tests |
| 3 — Frontend | #261 | Implemented | `CreditNotesPage`, ledger view button, invoice page badges, routing |
| 4 — Reporting | #263 | Implemented | Ledger statement impact, day-book, outstanding balance, reminder email |

> **Reporting note**: Credit notes now flow into ledger statements, the day book, and reminder outstanding calculations using the same item-level voucher semantics as invoice credits.

---

## Testing

```bash
# Backend
cd backend
python migrate.py up
pytest backend/tests -k "credit_note or financial_year or series" -v

# Frontend
cd frontend
npm run test:e2e
```

Key backend test cases:
- Multi-invoice CN creates `credit_note_invoice_refs` for each invoice
- Ledger mismatch on any invoice → 400
- Item `invoice_id` not in `invoice_ids` → 400
- Proportional GST reversal (partial/full, interstate/intrastate)
- Cumulative quantity limit across multiple CNs for same `invoice_item_id`
- `credit_status` recomputed for all referenced invoices on create and cancel
- `GET /api/credit-notes/?ledger_id=X` returns only CNs for that ledger
