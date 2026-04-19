# Cash & Bank Entries

This document describes the account-level debit/credit workflow in `/cash-bank`.

## What is supported

- Add debit/credit entries directly under a cash or bank account.
- Edit existing entries from the register.
- Delete entries (soft-cancel via payment status).
- Add a description for every entry using the existing `notes` field.

## Entry behavior

- Debit entry maps to `voucher_type = payment`.
- Credit entry maps to `voucher_type = receipt`.
- Description is stored in `notes`.
- Mode is set from selected account type (`cash` or `bank`).
- Account-only entries are allowed with:
  - `account_id` set
  - `ledger_id` omitted or `null`

## User flow in `/cash-bank`

1. Select an account in the Account filter.
2. Click `Add Entry` in the register header.
3. Choose entry type (`Debit` or `Credit`).
4. Enter amount, date, and description.
5. Save entry.
6. Use `Edit` or `Delete` actions on any row when needed.

## Validation rules

- Amount must be greater than 0.
- For payment creation, at least one of these must exist:
  - `ledger_id`, or
  - `account_id`
- `opening_balance` still requires a `ledger_id`.

## Data model notes

- `payments.buyer_id` is now nullable to support account-only entries.
- Existing ledger-linked payment flows remain unchanged.

## API examples

### Create account-only debit entry

```json
{
  "ledger_id": null,
  "voucher_type": "payment",
  "amount": 1200,
  "account_id": 3,
  "date": "2026-04-19T10:00:00",
  "mode": "cash",
  "notes": "ATM withdrawal"
}
```

### Create account-only credit entry

```json
{
  "ledger_id": null,
  "voucher_type": "receipt",
  "amount": 800,
  "account_id": 3,
  "date": "2026-04-20T09:30:00",
  "mode": "cash",
  "notes": "Counter deposit"
}
```
