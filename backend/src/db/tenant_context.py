"""The tenant a database session acts for, as seen by Postgres row-level security.

Shared hosting connects as a role that the policies in ``src/db/rls.py`` apply
to. Those policies compare each row's ``company_id`` with the transaction-local
setting ``app.company_id``, so a session sees nothing until it says which
company it is acting for -- and then sees only that company.

Why transaction-local, and why an ``after_begin`` hook:

- ``set_config(name, value, true)`` (the function form of ``SET LOCAL``) lasts
  until the transaction ends. A pooled connection handed to the next request
  therefore carries nothing over: the value is gone by the time the first
  request committed or rolled back, and the pool rolls back on check-in anyway.
  A session-level ``SET`` would survive check-in and leak one tenant's id into
  another tenant's request.
- Handlers commit mid-request (``db.commit()`` and carry on), which would drop
  the setting with it. So the values live in ``Session.info`` and the hook below
  re-applies them at the start of every transaction the session begins.

Nothing happens outside shared hosting or on a non-Postgres bind: single-tenant
deployments connect as the table owner, which row-level security never
constrains, and the test suite's SQLite has no ``set_config``.
"""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from src.core.config import settings

# Session.info key holding the values to apply.
INFO_KEY = "tenant_context"

# Python name -> Postgres setting. Every one is set on every transaction start
# (to '' when unset), so a value can never linger from earlier in a transaction.
#   company_id      the tenant every RLS'd row is matched against
#   user_id         who is acting; informational for now (no policy reads it)
#   share_token     a public share link being resolved before its company is known
#   api_key_prefix  an si_ API key being authenticated before its company is known
SETTINGS = {
    "company_id": "app.company_id",
    "user_id": "app.user_id",
    "share_token": "app.share_token",
    "api_key_prefix": "app.api_key_prefix",
}

_APPLY_SQL = text(
    "SELECT "
    + ", ".join(f"set_config('{name}', :{key}, true)" for key, name in SETTINGS.items())
)


def _enabled(bind) -> bool:
    return settings.is_shared_hosting and bind is not None and bind.dialect.name == "postgresql"


def _apply(connection, values: dict) -> None:
    connection.execute(
        _APPLY_SQL,
        {key: "" if values.get(key) is None else str(values[key]) for key in SETTINGS},
    )


def get_tenant_context(db: Session) -> dict:
    return dict(db.info.get(INFO_KEY) or {})


def set_tenant_context(db: Session, **values) -> None:
    """Merge ``values`` into this session's tenant context and apply it now.

    ``None`` clears a value. The context then holds for every later transaction
    of this session too, so a commit in the middle of a request keeps it.
    """
    unknown = set(values) - set(SETTINGS)
    if unknown:
        raise ValueError(f"Unknown tenant context key(s): {', '.join(sorted(unknown))}")
    context = dict(db.info.get(INFO_KEY) or {})
    context.update(values)
    db.info[INFO_KEY] = {key: value for key, value in context.items() if value is not None}

    if _enabled(db.get_bind()):
        # db.connection() begins a transaction if there is none, which runs the
        # hook below with the new values; applying again covers the case where a
        # transaction was already open. Either way the current one has them.
        _apply(db.connection(), db.info[INFO_KEY])


def clear_tenant_context(db: Session) -> None:
    set_tenant_context(db, **{key: None for key in SETTINGS})


@event.listens_for(Session, "after_begin")
def _reapply_on_begin(session: Session, transaction, connection) -> None:
    values = session.info.get(INFO_KEY)
    if values and _enabled(connection):
        _apply(connection, values)
