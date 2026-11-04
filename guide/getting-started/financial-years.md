# Financial years

Financial years run from 1 April to 31 March. They set the default dates for reports and statements, and each year has its own document numbering.

The **Financial Year** switcher is in the sidebar, below the company. Only admins can use it. Everyone else sees the active year as plain text.

## Switch the active year

Click the year and choose another. This changes the active year for the whole company and all its users, not just you.

## Add a new year

1. Click the year, then **+ New FY**.
2. Enter the **Starting year**. For 2026-27, enter 2026.
3. Click **Create**.
4. Choose the new year from the list. Creating a year does not make it active.

Numbering for the new year starts again at 1 and copies the format from the active year.

::: tip Before 1 April
Add the new year in late March and switch to it on 1 April, so reports and numbering are ready.
:::

If your series use the **FY** year format and the new label would make numbers too long for GSTR-1, the app warns you. The year is still created, so shorten the format in [Invoice series](./company-setup#invoice-series).

## Dates outside the active year

If you enter an invoice, receipt or payment dated outside the active year, you see a warning that the date is outside the active financial year, but the document is still saved. It takes its number from the year containing its date. This lets you enter a late invoice for last year without switching.

## There is no year-end closing

The app has no "close year" step and does not lock old years. Balances carry forward because statements add up everything dated before your chosen period. Opening balances entered on a ledger are dated at the start of the active year.

## No year showing?

If the switcher says **No active FY**, add one. New companies on the hosted version get the current year automatically, but on a self-hosted copy, a company created later does not.
