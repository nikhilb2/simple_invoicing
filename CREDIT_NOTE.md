# Credit Note Feature

## Overview

Credit notes allow adjusting previously issued invoices for returns, corrections, or discounts, with proportional GST reversal. A single credit note can cover **multiple invoices from the same ledger**.

Notes run in two **directions**:

| Direction | Against | What it is |
|-----------|---------|------------|
| `outward` | a sales invoice | A note **we issue**. Lowers our output tax and is filed in GSTR-1 (CDNR/CDNUR, and its series in Table 13). |
| `inward` | a purchase invoice | The **supplier's own** credit note, recorded on our side. Tally calls this voucher a Debit Note. |

Under s.34 CGST only the supplier issues a credit or debit note against their tax invoice, so there is **nothing for us to file** on an inward note: the supplier declares it in their GSTR-1 and it reaches us through GSTR-2B as a reduction of input credit. What we record is *their* document — their number and date are what reconcile against GSTR-2B — plus our own `DN-` number for the audit trail.

One note covers one voucher type; mixing sales and purchase invoices is rejected with a 400.

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
| `direction` | `outward\|inward` | Default `outward`; derived from the referenced invoices' `voucher_type` |
| `supplier_credit_note_number` | string nullable | The supplier's own number. Required on `inward`, rejected on `outward` |
| `supplier_credit_note_date` | date nullable | The supplier's own date. Same rule |
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
| `direction` | string | `outward` or `inward` (`outward` also matches rows predating the column) |
| `search` | string | ilike on credit_note_number **or** supplier_credit_note_number |
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

An inward note carries the supplier's document instead of a reason alone:

```json
{
  "ledger_id": 42,
  "invoice_ids": [305],
  "credit_note_type": "return",
  "direction": "inward",
  "supplier_credit_note_number": "SUP/CN/12",
  "supplier_credit_note_date": "2026-09-01",
  "items": [{ "invoice_id": 305, "invoice_item_id": 902, "quantity": 4 }]
}
```

**Validation rules:**
- All `invoice_ids` must belong to `ledger_id` → 400 if mismatch
- Each item's `invoice_id` must be in `invoice_ids` → 400 if mismatch
- Sum of existing active CN items + new quantity ≤ original item quantity per `invoice_item_id`
- All referenced invoices must share one `voucher_type` → 400 on a mix
- The declared `direction` must match what those invoices imply → 400 otherwise
- On `inward`, the same `supplier_credit_note_number` cannot already be active for that ledger → 400 (a duplicate would reverse the input credit twice)
- An invoice's `voucher_type` cannot be changed while active credit notes reference it → 400

---

## Frontend

### Pages & Routes

| Route | Page | Notes |
|-------|------|-------|
| `/credit-notes` | `CreditNotesPage.tsx` | Split: create form (left) + list (right). A **Voucher** select at the top of the form switches between Sales (outward) and Purchase (inward), and filters the invoice picker to that voucher type |
| `/credit-notes?ledger=<id>` | `CreditNotesPage.tsx` | Ledger pre-selected via `useSearchParams` |

Sidebar entry: **Credit / Debit Notes**, under Sales after Invoices — one page for both directions, the same shape as Invoices, which hosts purchases behind its own voucher toggle.

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

Two series, both scoped to the active financial year and configured like the invoice series (prefix, suffix, pad digits):

| Direction | `InvoiceSeries.voucher_type` | Default prefix |
|-----------|------------------------------|----------------|
| `outward` | `credit_note` | `CN` |
| `inward`  | `debit_note`  | `DN` |

They are kept apart because GSTR-1 Table 13 declares the outward series as a `from`/`to` range with a count. Numbers spent on documents we never issued would make that range wrong.

---

## Stock and Serials

A return undoes what its invoice did to stock, so the direction decides the sign:

| Direction | Source invoice did | The return does |
|-----------|--------------------|-----------------|
| `outward` | a sale took units out | brings them back in; sold serials return to `in_stock` |
| `inward`  | a purchase brought units in | sends them back out; serials are **voided**, as on a cancelled purchase |

Serials are voided rather than deleted: the unit existed and the note is the record of where it went, and a voided row sits outside `ux_product_serials_company_number`, so the supplier can ship the same IMEI again later. Cancelling the note reverses either movement, matching rows on the note text it stamped so one of several returns against the same invoice can be cancelled alone.

`discount` and `adjustment` notes do not move stock in either direction.

## Reporting

| Surface | Outward | Inward |
|---------|---------|--------|
| Party ledger / day book | Credits the ledger (receivable falls) | **Debits** the ledger (payable falls), labelled `Debit Note` and naming the supplier's number |
| Tax ledger | Reduces output tax | Reduces input credit, so GST payable rises |
| GSTR-1 | CDNR/CDNUR + Table 13 nature 5 | **Excluded entirely** |
| Invoice dues / reminders | Reduces the sales invoice's outstanding | Untouched — only ever touches a purchase invoice |

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
