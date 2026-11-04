# GSTR-3B worksheet

**Reports → GSTR-3B Worksheet** estimates the figures for your GSTR-3B from your own books, so you can compare them with the portal before you file.

::: danger A worksheet, not a return
It cannot be filed or uploaded, and there is no JSON export. Values auto-populated on the GST portal take precedence.
:::

![The GSTR-3B worksheet with warnings](/screens/gstr3b.webp)

## Use it

1. Choose **Last month**, **This month**, **Last quarter** or **This quarter**. Custom dates must be exactly one calendar month or one GST quarter.
2. Read **Why this may not match the portal** first. Each warning can list the documents behind it, and the CSV export lists all of them.
3. Check **Estimated cash payable** and **Credit carried forward** at the top, then the sections below.
4. Use **Export CSV** or **Export PDF** to keep a copy.

Amounts are always in rupees, whatever display currency your company uses.

## What it fills in

Each row is marked **From books** or **Not tracked**.

| Section | From your books |
|---|---|
| **3.1** Outward supplies | 3.1(a) taxable supplies, less credit notes issued. Sales at 0% appear on an unclassified line. |
| **3.2** Inter-state supplies | Nothing. All rows are Not tracked. |
| **4** Eligible input tax credit | 4(A)(5) all other ITC, and 4(C) net ITC. |
| **5** Exempt and non-GST inward supplies | Nothing. |
| **6.1** Payment of tax | An estimate, using the same set-off rules as the [Tax Ledger](./tax-ledger). |

## Known limits

- **Every purchase is treated as eligible credit.** Blocked credit under section 17(5) and reversals under rules 37, 38, 42 and 43 are not recorded, so your credit can look too high.
- **It uses your entries, not GSTR-2B.** The portal's Table 4 follows GSTR-2B, while this follows your purchase entries by booking date. The app does not reconcile against GSTR-2B.
- **Some things are not recorded:** reverse charge, imports, ISD, exports, SEZ and cess.
- **Credit from earlier periods is left out** of the 6.1 estimate, as is any negative liability carried forward.
- **Older sales may have no place of supply**, which can affect how they are classified.
