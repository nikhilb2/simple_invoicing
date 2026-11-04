# Troubleshooting

## Signing in

**I did not get the verification email.**
Check your spam folder, then use **Resend verification email**. The link lasts 24 hours.

**"Invalid credentials".**
The email or password is wrong. Use **Forgot password?**. If you signed up with Google, use **Continue with Google**.

**"Please verify your email address before signing in".**
Open the link in your email, or use the **Resend verification email** button on that page.

**"Too many attempts".**
Wait a few minutes and try again.

**The app sends me back to the dashboard when I open a page.**
Your role does not allow that page. See [Roles](../getting-started/team#roles). On a self-hosted copy, refreshing the browser on the Email or Backups page can also do this, so open them again from **Settings**.

## Invoices

**The total or tax split looks wrong.**
Check the [Place of supply](../sales/invoices#how-gst-is-split). An unregistered customer defaults to your own state. Also check **Prices include GST**, which your browser remembers from the last invoice.

**"Insufficient inventory".**
You have less stock than the invoice needs. Record the purchase or [adjust the stock](../catalogue/products#adjust-stock).

**An invoice shows as overdue the day after I made it.**
It has no real credit period, because **No due date** saves the invoice date as the due date. [Edit it](../sales/invoices#edit-pencil) and set the days under **Advanced options**.

**I cannot find an invoice.**
The [Invoice Feed](../sales/invoice-feed) only shows the active financial year and leaves out cancelled invoices. Under **Filters**, tick **Search all FY** and **Show cancelled**.

**An invoice cannot move to another date.**
It cannot cross into a different financial year. Cancel it and create a new one in the right year.

**A customer paid but still shows on Dues.**
Allocate the receipt to the invoice. Open the ledger, then edit the receipt. See [Record a receipt](../sales/cash-bank#record-a-receipt-against-invoices).

**A product is not on my invoice's list, or its GST is wrong.**
The GST rate and HSN come from the product. [Edit the product](../catalogue/products#change-a-product), then save the invoice again.

## GST

**GSTR-1 says the period is not a return period.**
Choose one whole month, or one whole quarter starting in January, April, July or October.

**"HSN is not on GST's list".**
[Correct the HSN on the product](../catalogue/products#change-a-product), then open and save the invoice again.

**The JSON export is refused.**
The export checks again. Fix the listed errors. Also check that your company's [GSTIN](../getting-started/company-setup) is valid.

**The portal rejected my file, or sent an error report.**
Correct those invoices in the app, export and upload again. The app cannot read portal error reports, so you need to match them up by hand.

**My GSTR-3B worksheet differs from the portal.**
That is expected. The portal's figures take precedence. See the [known limits](../reports/gstr3b#known-limits).

**Can the app file my returns?**
No. It prepares the GSTR-1 file and the GSTR-3B estimate. You file on the GST portal.

## Stock

**I cannot change a stock figure.**
Click the stock number and make an [adjustment](../catalogue/products#adjust-stock). Stock is not edited directly.

**I cannot delete a product or ledger.**
It has history. See [products](../catalogue/products#delete-a-product) and [ledgers](../ledgers/#delete-a-ledger).

## Email

**"Daily email limit reached".**
The hosted version allows 50 emails per company in any 24 hours. Try again later, or [share a link](../sales/sending#share-a-link-or-send-on-whatsapp) instead.

**"No active SMTP configuration found".**
On a self-hosted copy, [add a configuration and set it as active](../settings/email#on-a-self-hosted-copy).

**Did my email send?**
Check [Email History](../settings/email#email-history). The dialog simply closes on success.

## Still stuck?

Click **Request a feature or report a bug** at the top of any page, or [open an issue on GitHub](https://github.com/nikhilb2/simple_invoicing/issues). Please describe what you did and what you saw, and do not post customer details in the issue, because issues are public.
