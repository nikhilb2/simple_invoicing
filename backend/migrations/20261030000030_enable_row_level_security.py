"""
Shared hosting: enable Postgres row-level security on every tenant table.

Defence in depth for the public multi-tenant instance. The policies, and the
reasoning for which tables are covered and which are deliberately left out
(users, memberships, OAuth tables, company_profiles, global settings, SMTP
config, _migrations), live in src/db/rls.py so that boot (app_main) and this
migration apply exactly the same thing.

Single-tenant databases are left untouched: RLS is never enabled there. Their
app connects as the table owner, which RLS would not constrain anyway, and not
enabling it at all means no policy can ever surprise a deployment whose role
setup differs. A database switched to shared hosting later gets the policies on
its first shared-hosting boot, which runs the same idempotent step.

Never FORCE ROW LEVEL SECURITY: the owner must keep seeing every row for
migrations, pg_dump and restore.

Grants are not handled here. Tables created after this run as the owner, and
the app role (invoicing_app) needs SELECT/INSERT/UPDATE/DELETE on them and
USAGE on their sequences: set up once with ALTER DEFAULT PRIVILEGES, as the
si-common deployment README describes. The shared-hosting boot check refuses to
start when a grant is missing.
"""

from src.core.config import settings
from src.db.rls import POLICY_NAME, ensure_row_level_security, protected_tables
from sqlalchemy import text


def up(conn) -> None:
    if not settings.is_shared_hosting:
        return
    ensure_row_level_security(conn)


def down(conn) -> None:
    if conn.dialect.name != "postgresql":
        return
    for table in protected_tables():
        conn.execute(text(
            f"DO $$ BEGIN IF to_regclass('{table}') IS NOT NULL THEN "
            f"EXECUTE 'DROP POLICY IF EXISTS {POLICY_NAME} ON {table}'; "
            f"EXECUTE 'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY'; END IF; END $$"
        ))
