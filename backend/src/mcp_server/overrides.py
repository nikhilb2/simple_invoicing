"""Hand-written names, descriptions, exclusions and the "core" profile.

The generated names in :mod:`src.mcp_server.naming` are deterministic but not
always readable; this table fixes the ones a model would misread, and supplies
the one-line descriptions the routes themselves do not carry (no route in this
codebase sets ``summary=`` or ``description=``, so without this every tool would
ship with an empty description and the model would be guessing).

Keys are ``(METHOD, path)`` exactly as they appear in ``app.openapi()``.
"""

from __future__ import annotations

# --- exclusions -----------------------------------------------------------
# Excluded at the *registry*, never by scope: scopes are a consent artifact and
# consent gets clicked through.
EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (
    # Restoring a backup overwrites the entire database from an uploaded archive.
    "/api/backups",
    # A tool that mints `si_` keys lets a model manufacture a credential that
    # bypasses the whole OAuth scope model — privilege escalation by design.
    "/api/api-keys",
    # The OAuth authorization server itself. Its routes are include_in_schema=False
    # today, so nothing is generated from them anyway; this is the belt to that
    # braces, because a tool that mints or revokes tokens is the same privilege
    # escalation as an API-key minting tool.
    "/api/oauth",
    "/.well-known",
)

EXCLUDED_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # Credential handling. GET /api/auth/me survives, renamed `whoami`.
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/refresh"),
        ("POST", "/api/auth/change-password"),
        # Persistently mutates which company the human sees in the web UI.
        ("POST", "/api/company/select/{company_id}"),
    }
)

# --- names ----------------------------------------------------------------
NAME_OVERRIDES: dict[tuple[str, str], str] = {
    ("GET", "/api/auth/me"): "whoami",
    ("GET", "/api/health"): "health_check",
    # company
    ("GET", "/api/company/"): "company_get_profile",
    ("PUT", "/api/company/"): "company_update_profile",
    ("GET", "/api/company/companies"): "companies_list",
    ("POST", "/api/company/companies"): "companies_create",
    ("GET", "/api/company/companies/capability"): "companies_can_create",
    ("PUT", "/api/company/logo"): "company_set_logo",
    ("DELETE", "/api/company/logo"): "company_remove_logo",
    ("POST", "/api/company/terms"): "company_create_term",
    ("PUT", "/api/company/terms/{term_id}"): "company_update_term",
    ("DELETE", "/api/company/terms/{term_id}"): "company_delete_term",
    # invoices
    ("DELETE", "/api/invoices/{invoice_id}"): "invoices_cancel",
    ("GET", "/api/invoices/export"): "invoices_export_csv",
    ("GET", "/api/invoices/{invoice_id}/pdf"): "invoices_download_pdf",
    ("POST", "/api/invoices/{invoice_id}/duplicate"): "invoices_duplicate",
    ("POST", "/api/invoices/{invoice_id}/restore"): "invoices_restore",
    # ledgers
    ("GET", "/api/ledgers/day-book"): "ledgers_day_book",
    ("GET", "/api/ledgers/day-book/csv"): "ledgers_day_book_csv",
    ("GET", "/api/ledgers/day-book/pdf"): "ledgers_day_book_pdf",
    ("GET", "/api/ledgers/tax-ledger/"): "tax_ledger_get",
    ("GET", "/api/ledgers/tax-ledger/csv"): "tax_ledger_csv",
    ("GET", "/api/ledgers/tax-ledger/pdf"): "tax_ledger_pdf",
    ("GET", "/api/ledgers/tax-ledger/gstr1/export-csv"): "gstr1_export_csv",
    ("GET", "/api/ledgers/tax-ledger/gstr1/export-json"): "gstr1_export_json",
    ("GET", "/api/ledgers/tax-ledger/gstr1/export-pdf"): "gstr1_export_pdf",
    ("GET", "/api/ledgers/tax-ledger/gstr1/summary"): "gstr1_summary",
    ("GET", "/api/ledgers/tax-ledger/gstr1/validate"): "gstr1_validate",
    ("GET", "/api/ledgers/{ledger_id}/statement/pdf"): "ledgers_download_statement_pdf",
    ("GET", "/api/ledgers/{ledger_id}/addresses/"): "ledgers_list_addresses",
    ("POST", "/api/ledgers/{ledger_id}/addresses/"): "ledgers_create_address",
    ("PUT", "/api/ledgers/{ledger_id}/addresses/{address_id}"): "ledgers_update_address",
    ("DELETE", "/api/ledgers/{ledger_id}/addresses/{address_id}"): "ledgers_delete_address",
    # products / inventory
    ("GET", "/api/products/export-csv"): "products_export_csv",
    ("POST", "/api/inventory/adjust"): "inventory_adjust",
    ("POST", "/api/inventory/produce"): "inventory_produce",
    ("GET", "/api/inventory/production-history"): "inventory_production_history",
    ("GET", "/api/bom/product/{product_id}"): "bom_get_for_product",
    # payments
    ("GET", "/api/payments/{payment_id}/pdf"): "payments_download_receipt_pdf",
    # credit notes
    ("POST", "/api/credit-notes/{cn_id}/cancel"): "credit_notes_cancel",
    # shortcuts — DELETE /api/shortcuts/ and DELETE /api/shortcuts/{action_key}
    # both generate `shortcuts_delete`; this is the one real collision.
    ("DELETE", "/api/shortcuts/"): "shortcuts_delete_all",
    # smtp
    ("GET", "/api/smtp-configs/"): "smtp_get_config",
    ("POST", "/api/smtp-configs/"): "smtp_create_config",
    ("PUT", "/api/smtp-configs/{smtp_config_id}"): "smtp_update_config",
    ("DELETE", "/api/smtp-configs/{smtp_config_id}"): "smtp_delete_config",
    ("POST", "/api/smtp-configs/{smtp_config_id}/activate"): "smtp_activate_config",
    ("POST", "/api/smtp-configs/test"): "smtp_test_connection",
    ("POST", "/api/smtp-configs/test-template"): "smtp_test_template",
    # email
    ("POST", "/api/email/due-reminders"): "email_send_due_reminders",
    ("POST", "/api/email/invoice/{invoice_id}"): "email_send_invoice",
    ("POST", "/api/email/ledger-statement/{ledger_id}"): "email_send_ledger_statement",
    ("POST", "/api/email/payment-reminder/{ledger_id}"): "email_send_payment_reminder",
    # financial years
    ("PUT", "/api/financial-years/{fy_id}/activate"): "financial_years_activate",
    # analytics / dashboard
    ("GET", "/api/analytics/profit-loss"): "analytics_profit_loss",
    ("GET", "/api/analytics/profit-loss/csv"): "analytics_profit_loss_csv",
    ("GET", "/api/analytics/sales-by-month"): "analytics_sales_by_month",
    ("GET", "/api/analytics/sales-by-month/csv"): "analytics_sales_by_month_csv",
    ("GET", "/api/analytics/sales-by-product"): "analytics_sales_by_product",
    ("GET", "/api/analytics/sales-by-product/csv"): "analytics_sales_by_product_csv",
    ("GET", "/api/dashboard/metrics"): "dashboard_metrics",
    # serials
    ("GET", "/api/serials/scan"): "serials_scan",
    # marketplace
    ("GET", "/api/marketplace/catalog"): "marketplace_browse_catalog",
    ("GET", "/api/marketplace/catalog/{listing_id}"): "marketplace_get_catalog_listing",
    ("GET", "/api/marketplace/connection"): "marketplace_get_connection",
    ("POST", "/api/marketplace/connection"): "marketplace_register_connection",
    ("PATCH", "/api/marketplace/connection"): "marketplace_update_connection",
    ("DELETE", "/api/marketplace/connection"): "marketplace_delete_connection",
    ("GET", "/api/marketplace/connection/meta"): "marketplace_get_meta",
    ("POST", "/api/marketplace/connection/rotate-key"): "marketplace_rotate_key",
    ("POST", "/api/marketplace/listings"): "marketplace_create_listing",
    ("PATCH", "/api/marketplace/listings/{listing_id}"): "marketplace_update_listing",
    ("DELETE", "/api/marketplace/listings/{listing_id}"): "marketplace_delete_listing",
    ("POST", "/api/marketplace/orders"): "marketplace_create_order",
    ("GET", "/api/marketplace/orders/{order_id}"): "marketplace_get_order",
    ("POST", "/api/marketplace/orders/{order_id}/accept"): "marketplace_accept_order",
    ("POST", "/api/marketplace/orders/{order_id}/cancel"): "marketplace_cancel_order",
    ("POST", "/api/marketplace/orders/{order_id}/reject"): "marketplace_reject_order",
    ("POST", "/api/marketplace/orders/{order_id}/link-product"): "marketplace_link_order_product",
    ("POST", "/api/marketplace/orders/{order_id}/retry-posting"): "marketplace_retry_order_posting",
    ("POST", "/api/marketplace/sync"): "marketplace_sync",
    ("POST", "/api/marketplace/sync-all"): "marketplace_sync_all",
}

# --- descriptions ---------------------------------------------------------
DESCRIPTION_OVERRIDES: dict[tuple[str, str], str] = {
    ("GET", "/api/auth/me"): "Return the authenticated user: id, email, role and active company.",
    ("GET", "/api/health"): "Liveness probe. Returns {'status': 'ok'}.",
    # invoices
    ("GET", "/api/invoices/"): (
        "List sales/purchase invoices for the active company, newest first. Supports "
        "free-text `search` over invoice number and party name, plus date, product and "
        "financial-year filters. Paginated."
    ),
    ("GET", "/api/invoices/{invoice_id}"): "Fetch one invoice in full, including its line items and totals.",
    ("POST", "/api/invoices/"): "Create an invoice with its line items. Allocates the next number in the active series.",
    ("PUT", "/api/invoices/{invoice_id}"): "Replace an existing invoice's fields and line items.",
    ("DELETE", "/api/invoices/{invoice_id}"): "Cancel an invoice. It stays in the books as a cancelled voucher.",
    ("GET", "/api/invoices/dues"): "List invoices with an outstanding balance, for chasing payment.",
    ("GET", "/api/invoices/export"): "Export the filtered invoice list as CSV.",
    ("GET", "/api/invoices/{invoice_id}/pdf"): "Render an invoice as a PDF document.",
    ("POST", "/api/invoices/{invoice_id}/duplicate"): "Copy an invoice into a new draft with a fresh number and today's date.",
    ("POST", "/api/invoices/{invoice_id}/restore"): "Un-cancel a previously cancelled invoice.",
    # ledgers
    ("GET", "/api/ledgers/"): "List ledgers (customers, suppliers and account heads). Supports free-text `search`.",
    ("GET", "/api/ledgers/{ledger_id}"): "Fetch one ledger with its balance and contact details.",
    ("POST", "/api/ledgers/"): "Create a ledger (customer, supplier or account head).",
    ("PUT", "/api/ledgers/{ledger_id}"): "Update a ledger's details.",
    ("DELETE", "/api/ledgers/{ledger_id}"): "Delete a ledger. Fails if it carries transactions.",
    ("GET", "/api/ledgers/{ledger_id}/statement"): "Account statement for one ledger over a date range, with running balance.",
    ("GET", "/api/ledgers/{ledger_id}/unpaid-invoices"): "Invoices for this ledger that still have an amount outstanding.",
    ("GET", "/api/ledgers/day-book"): "Day book: every voucher posted on a given date or date range.",
    ("GET", "/api/ledgers/tax-ledger/"): "Tax ledger: output and input GST by period.",
    ("GET", "/api/ledgers/tax-ledger/gstr1/summary"): "GSTR-1 summary totals for the selected return period.",
    ("GET", "/api/ledgers/tax-ledger/gstr1/validate"): "Validate invoices against GSTR-1 filing rules and list the problems found.",
    ("GET", "/api/ledgers/tax-ledger/gstr1/export-json"): "GSTR-1 return as the GST portal's JSON upload format.",
    # products / inventory
    ("GET", "/api/products/"): "List products for the active company. Supports free-text `search` over name and SKU.",
    ("GET", "/api/products/with-inventory"): "List products joined with live stock levels, sortable and filterable by stock status.",
    ("POST", "/api/products/"): "Create a product.",
    ("PUT", "/api/products/{product_id}"): "Update a product's details.",
    ("DELETE", "/api/products/{product_id}"): "Delete a product.",
    ("GET", "/api/inventory/"): "Current stock on hand per product.",
    ("POST", "/api/inventory/adjust"): "Post a manual stock adjustment (positive or negative) against a product.",
    ("POST", "/api/inventory/produce"): "Record production of a finished item, consuming its bill of materials.",
    # payments
    ("GET", "/api/payments/"): "List payment receipts and disbursements. Filter by ledger.",
    ("GET", "/api/payments/{payment_id}"): "Fetch one payment with its invoice allocations.",
    ("POST", "/api/payments/"): "Record a payment received or made, optionally allocated against invoices.",
    # credit notes
    ("GET", "/api/credit-notes/"): "List credit notes. Supports free-text `search` and status/date filters.",
    ("GET", "/api/credit-notes/{cn_id}"): "Fetch one credit note with its line items.",
    ("POST", "/api/credit-notes/"): "Raise a credit note against an invoice or a ledger.",
    # serials
    ("GET", "/api/serials/"): "List tracked serial/IMEI units. Filter by product or status; supports free-text `search`.",
    ("GET", "/api/serials/scan"): "Resolve a scanned barcode to a serial unit, or failing that to a product SKU.",
    # company
    ("GET", "/api/company/"): "The active company's profile: name, address, GST number, bank details.",
    ("GET", "/api/company/companies"): "List the companies this user can act for.",
    # reporting
    ("GET", "/api/dashboard/metrics"): "Headline dashboard metrics: sales, receivables, stock value and recent activity.",
    ("GET", "/api/analytics/profit-loss"): "Profit and loss statement for a date range.",
    ("GET", "/api/analytics/sales-by-month"): "Monthly sales totals over a date range.",
    ("GET", "/api/analytics/sales-by-product"): "Sales totals grouped by product over a date range.",
    # email — real, irreversible mail to real customers
    ("POST", "/api/email/invoice/{invoice_id}"): "Send an invoice by email to the customer. Sends real mail; not reversible.",
    ("POST", "/api/email/ledger-statement/{ledger_id}"): "Email an account statement to a ledger's contact. Sends real mail; not reversible.",
    ("POST", "/api/email/payment-reminder/{ledger_id}"): "Email a payment reminder to a ledger's contact. Sends real mail; not reversible.",
    ("POST", "/api/email/due-reminders"): "Email due reminders in bulk to every party with an overdue balance. Sends real mail; not reversible.",
    # marketplace
    ("POST", "/api/marketplace/sync-all"): "Sync every marketplace connection. Makes outbound HTTP calls and can run for a while.",
}

# --- annotation nudges ----------------------------------------------------
# Operations that send real, irreversible email. Gated by `invoicing:send_email`
# rather than the general write scope, and flagged destructive.
EMAIL_PATH_PREFIX = "/api/email/"

# Operations that reach outside this server.
OPEN_WORLD_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/marketplace/sync"),
        ("POST", "/api/marketplace/sync-all"),
        ("POST", "/api/smtp-configs/test"),
        ("POST", "/api/smtp-configs/test-template"),
        ("GET", "/api/marketplace/catalog"),
        ("GET", "/api/marketplace/catalog/{listing_id}"),
    }
)

# --- the "core" profile ---------------------------------------------------
# MCP_DEFAULT_PROFILE="core" ships this curated set instead of all ~130 tools —
# a smaller list the model can actually hold in its head. `search` and `fetch`
# are always present and are not listed here.
CORE_TOOLS: frozenset[str] = frozenset(
    {
        "whoami",
        "company_get_profile",
        "companies_list",
        # invoices
        "invoices_list",
        "invoices_get",
        "invoices_list_dues",
        "invoices_export_csv",
        "invoices_download_pdf",
        "invoices_create",
        "invoices_update",
        "invoices_cancel",
        # ledgers
        "ledgers_list",
        "ledgers_get",
        "ledgers_get_statement",
        "ledgers_get_unpaid_invoices",
        "ledgers_create",
        "ledgers_update",
        # products & stock
        "products_list",
        "products_list_with_inventory",
        "products_create",
        "products_update",
        "inventory_list",
        "inventory_adjust",
        "serials_list",
        "serials_scan",
        # money
        "payments_list",
        "payments_get",
        "payments_create",
        "credit_notes_list",
        "credit_notes_get",
        "credit_notes_create",
        # reporting
        "dashboard_metrics",
        "analytics_profit_loss",
        "analytics_sales_by_month",
        "analytics_sales_by_product",
        "ledgers_day_book",
        "tax_ledger_get",
        "gstr1_summary",
        # email
        "email_send_invoice",
    }
)
