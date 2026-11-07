"""Postgres row-level security for shared hosting: the policies and the boot check.

Defence in depth under the application-level checks in
``src/services/company_access.py``. If a query anywhere forgets its
``company_scope`` filter, the database still returns only the rows of the
company the session is acting for (``app.company_id``, set per transaction by
``src/db/tenant_context.py``).

Only shared hosting gets any of this. A single-tenant database is one
customer's, its app connects as the table owner, and it never has RLS enabled.

What is covered
---------------
Every business table with a ``company_id`` (``DIRECT_TABLES``), plus the child
tables that have none and reach their company through a parent
(``CHILD_TABLES``). The policy is plain equality, so a row with a NULL
``company_id`` belongs to nobody and is never visible, and an INSERT or UPDATE
that would leave a row outside the current company is refused (WITH CHECK).

Two tables are read before the company is known, by a credential that names a
row directly, so their policy also admits the row that credential names:

- ``share_links``: a public share page resolves its token with no signed-in
  user; ``app.share_token`` admits that one link, whose ``company_id`` then
  becomes the context.
- ``api_keys``: authenticating an ``si_`` key looks it up by its prefix;
  ``app.api_key_prefix`` admits the keys with that prefix (the caller holds the
  full key), and the key's company becomes the context.

What is deliberately not covered
--------------------------------
Platform tables, read across companies by design, before any tenant is chosen:

- ``users``, ``company_memberships``, ``user_identities``, ``oauth_login_codes``:
  sign-in, signup and membership checks run before there is a company.
- ``oauth_clients``, ``oauth_auth_requests``, ``oauth_authorization_codes``,
  ``oauth_tokens``: the MCP authorization server resolves a bearer token to a
  user and company before any request context exists.
- ``company_profiles``: the tenant root. A user lists, selects and creates
  companies with no single company in context, and an INSERT ... RETURNING of a
  new company would fail any membership-keyed policy, since the membership row
  can only be written after it. Access is decided by ``can_access_company`` on
  every path instead.
- ``global_settings``, ``smtp_configs``: deployment-wide configuration.
- ``user_shortcuts``: per user, no company.
- ``_migrations``: the migration ledger.

Never FORCE ROW LEVEL SECURITY: the owner (MIGRATION_DATABASE_URL) must keep
seeing every row, for migrations, pg_dump and restore.
"""

from __future__ import annotations

from sqlalchemy import text

POLICY_NAME = "si_tenant_isolation"

# The company this transaction acts for, or NULL. NULLIF matters: once a
# connection has set app.company_id even transaction-locally, the setting reverts
# to '' rather than NULL, and ''::int would raise instead of matching nothing.
CURRENT_COMPANY = "NULLIF(current_setting('app.company_id', true), '')::int"

DIRECT_TABLES: tuple[str, ...] = (
    "bill_of_materials",
    "buyers",
    "company_accounts",
    "company_terms",
    "credit_note_items",
    "credit_notes",
    "email_logs",
    "eway_bill_transporters",
    "financial_years",
    "inventory",
    "invoice_series",
    "invoices",
    "ledger_addresses",
    "marketplace_connections",
    "marketplace_ledger_links",
    "marketplace_listings",
    "marketplace_orders",
    "marketplace_processed_events",
    "marketplace_product_links",
    "payments",
    "product_serials",
    "production_transactions",
    "products",
    "quotations",
)

# table -> (foreign key column, parent table). The parent's own company_id
# decides; an EXISTS on the parent's primary key is one index probe per row.
# Kept as joins rather than new company_id columns: every one of these is only
# ever read through its parent, the parent lookup is by primary key, and a
# duplicated column would be one more thing every write path has to keep right.
CHILD_TABLES: dict[str, tuple[str, str]] = {
    "invoice_items": ("invoice_id", "invoices"),
    "quotation_items": ("quotation_id", "quotations"),
    "credit_note_invoice_refs": ("credit_note_id", "credit_notes"),
    "payment_invoice_allocations": ("payment_id", "payments"),
    "marketplace_order_items": ("order_id", "marketplace_orders"),
}

# Tables read before the company is known: equality on company_id, or the one
# row the caller's credential names.
CREDENTIAL_TABLES: dict[str, str] = {
    "share_links": "token = NULLIF(current_setting('app.share_token', true), '')",
    "api_keys": "key_prefix = NULLIF(current_setting('app.api_key_prefix', true), '')",
}

EXCLUDED_TABLES: tuple[str, ...] = (
    "_migrations",
    "company_memberships",
    "company_profiles",
    "global_settings",
    "oauth_auth_requests",
    "oauth_authorization_codes",
    "oauth_clients",
    "oauth_login_codes",
    "oauth_tokens",
    "smtp_configs",
    "tax_withholding_sections",  # Shared tax reference data, not company data.
    "user_identities",
    "user_shortcuts",
    "users",
)


def protected_tables() -> tuple[str, ...]:
    return tuple(sorted({*DIRECT_TABLES, *CHILD_TABLES, *CREDENTIAL_TABLES}))


def policy_expression(table: str) -> str:
    if table in DIRECT_TABLES:
        return f"company_id = {CURRENT_COMPANY}"
    if table in CHILD_TABLES:
        fk, parent = CHILD_TABLES[table]
        return (
            f"EXISTS (SELECT 1 FROM {parent} parent "
            f"WHERE parent.id = {table}.{fk} AND parent.company_id = {CURRENT_COMPANY})"
        )
    if table in CREDENTIAL_TABLES:
        return f"(company_id = {CURRENT_COMPANY} OR {CREDENTIAL_TABLES[table]})"
    raise KeyError(table)


def ensure_row_level_security(conn) -> list[str]:
    """Create any missing policy and enable RLS where it is off. Idempotent.

    Looks before it alters, so on an up-to-date database it takes no locks and
    changes nothing: it runs on every shared-hosting boot (and from migration
    20261030000030), possibly from several replicas at once. Returns the
    statements it executed. Must run as the table owner.
    """
    if conn.dialect.name != "postgresql":
        return []

    tables = protected_tables()
    # Replicas boot together: serialise them, so the second one to get here
    # sees the first one's policies instead of failing on "already exists".
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('si_tenant_isolation'))"))
    rows = conn.execute(
        text(
            "SELECT c.relname, c.relrowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') "
            "AND c.relname = ANY(:names)"
        ),
        {"names": list(tables)},
    ).fetchall()
    rls_enabled = {name: enabled for name, enabled in rows}
    with_policy = {
        row[0]
        for row in conn.execute(
            text(
                "SELECT tablename FROM pg_policies "
                "WHERE schemaname = current_schema() AND policyname = :policy"
            ),
            {"policy": POLICY_NAME},
        ).fetchall()
    }

    executed: list[str] = []
    for table in tables:
        if table not in rls_enabled:
            continue  # not created on this database (yet)
        if table not in with_policy:
            expression = policy_expression(table)
            executed.append(
                f"CREATE POLICY {POLICY_NAME} ON {table} "
                f"USING ({expression}) WITH CHECK ({expression})"
            )
        if not rls_enabled[table]:
            executed.append(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    for statement in executed:
        conn.execute(text(statement))
    return executed


def app_role_problems(conn) -> list[str]:
    """Why the connected role would not be constrained by RLS, or [] if it would.

    Run on the APPLICATION connection (DATABASE_URL) at shared-hosting boot.
    Row-level security does not apply to superusers, to roles with BYPASSRLS, or
    to a table's owner -- including any role that is a member of the owner role,
    since it can SET ROLE to it. Any one of those means every policy is off for
    the app, silently, so the app refuses to start instead.
    """
    if conn.dialect.name != "postgresql":
        return []

    problems: list[str] = []
    role, is_super, bypass = conn.execute(
        text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    if is_super:
        problems.append(f"role {role!r} is a superuser")
    if bypass:
        problems.append(f"role {role!r} has BYPASSRLS")

    tables = list(protected_tables())
    owned = [
        row[0]
        for row in conn.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = ANY(:names) "
                "AND pg_has_role(current_user, c.relowner, 'MEMBER') "
                "ORDER BY c.relname"
            ),
            {"names": tables},
        ).fetchall()
    ]
    if owned:
        problems.append(f"role {role!r} owns (or is a member of the owner of) {', '.join(owned)}")

    present = conn.execute(
        text(
            "SELECT c.relname, c.relrowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relname = ANY(:names) ORDER BY c.relname"
        ),
        {"names": tables},
    ).fetchall()
    unprotected = [name for name, enabled in present if not enabled]
    if unprotected:
        problems.append(f"row-level security is not enabled on {', '.join(unprotected)}")
    missing = sorted(set(tables) - {name for name, _ in present})
    if missing:
        problems.append(f"tables are missing: {', '.join(missing)}")

    no_grants = [
        row[0]
        for row in conn.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relkind = 'r' "
                # One call per privilege: given a list, has_table_privilege is
                # true when ANY of them is held.
                "AND NOT (has_table_privilege(current_user, c.oid, 'SELECT') "
                "AND has_table_privilege(current_user, c.oid, 'INSERT') "
                "AND has_table_privilege(current_user, c.oid, 'UPDATE') "
                "AND has_table_privilege(current_user, c.oid, 'DELETE')) "
                "ORDER BY c.relname"
            )
        ).fetchall()
    ]
    if no_grants:
        problems.append(
            f"role {role!r} lacks SELECT/INSERT/UPDATE/DELETE on {', '.join(no_grants)} "
            "(see the ALTER DEFAULT PRIVILEGES grants in the deployment README)"
        )

    no_sequence_grants = [
        row[0]
        for row in conn.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relkind = 'S' "
                "AND NOT has_sequence_privilege(current_user, c.oid, 'USAGE') "
                "ORDER BY c.relname"
            )
        ).fetchall()
    ]
    if no_sequence_grants:
        problems.append(
            f"role {role!r} lacks USAGE on sequences {', '.join(no_sequence_grants)}, "
            "so it cannot insert into their tables"
        )
    return problems


def check_app_role_or_raise(conn) -> None:
    problems = app_role_problems(conn)
    if problems:
        raise RuntimeError(
            "Refusing to start in shared_hosting: the DATABASE_URL role is not constrained "
            "by row-level security, so tenants would not be isolated in the database. "
            + "; ".join(problems)
            + ". Connect as a non-owner role without BYPASSRLS (invoicing_app) and run "
            "migrations through MIGRATION_DATABASE_URL. For local development only, "
            "RLS_BOOT_CHECK=false skips this check."
        )
