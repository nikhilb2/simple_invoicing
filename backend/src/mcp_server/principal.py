"""The identity behind an MCP request, and how it is resolved.

This module is the single documented seam between the MCP track and the OAuth
authorization-server track. It exports exactly three names — :class:`Principal`,
:class:`Unauthenticated` and :func:`resolve_principal` — and imports the OAuth
side lazily so this package keeps importing cleanly before that track lands.

:func:`resolve_principal` is deliberately a plain module-level function and *not*
a FastAPI dependency: the transport calls it by hand before any JSON-RPC parsing
happens (a 401 must be a real HTTP 401, not a 200 carrying a tool error), and a
plain function is trivially monkeypatchable from tests.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Principal:
    """A frozen snapshot of the consenting user — never a live ORM object.

    Holding a live ``User`` would keep its ``Session`` (and its database
    connection) open for the whole tool call; under pytest's ``StaticPool``
    SQLite that deadlocks the in-process dispatch against itself.
    """

    user_id: int
    email: str
    role: str
    company_id: int | None
    scopes: frozenset[str]
    client_id: str | None = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def has_all_scopes(self, scopes) -> bool:
        return all(scope in self.scopes for scope in scopes)


class Unauthenticated(Exception):
    """No usable bearer token on the request.

    The transport turns this into a real HTTP 401 plus the ``WWW-Authenticate``
    challenge that starts the OAuth flow in the client.
    """


def bearer_token(request) -> str | None:
    """Extract a bearer token from the Authorization header, if present."""
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


@contextmanager
def session_for(request):
    """Yield a database session bound to whatever database *this app* is using.

    The transport calls this outside the dependency-injection graph, so it has to
    resolve the session itself. It honours ``app.dependency_overrides[get_db]``
    when one is installed — that override is how the app's database is
    configured under test, and a principal resolved against a different database
    than the one dispatch will hit is not a principal at all.
    """
    from src.db.session import SessionLocal, get_db

    app = getattr(request, "app", None)
    override = getattr(app, "dependency_overrides", {}).get(get_db) if app is not None else None

    if override is None:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
        return

    produced = override()
    if hasattr(produced, "__next__"):
        db = next(produced)
        try:
            yield db
        finally:
            try:
                next(produced)
            except StopIteration:
                pass
    else:  # pragma: no cover - a plain callable override
        yield produced


async def resolve_principal(request) -> Principal:
    """Resolve the request's bearer token to a :class:`Principal`.

    Raises :class:`Unauthenticated` when there is no token, when the token does
    not resolve, or when the OAuth track is not installed yet.
    """
    token = bearer_token(request)
    if token is None:
        raise Unauthenticated("Missing bearer token")

    try:
        # Function-local so this module imports cleanly before the OAuth track
        # lands — the two tracks are built in parallel.
        from src.services.oauth.tokens import resolve_bearer
    except ImportError:
        logger.warning(
            "MCP: OAuth token service is not available; every request will be challenged."
        )
        raise Unauthenticated("OAuth token service unavailable")

    # Closed *before* returning: the session must not survive into dispatch,
    # which opens its own per-request session inside the same app. Under
    # pytest's StaticPool SQLite, holding it would deadlock against itself.
    with session_for(request) as db:
        oauth_principal = resolve_bearer(token, db)
        if oauth_principal is None:
            raise Unauthenticated("Invalid or expired bearer token")
        principal = Principal(
            user_id=oauth_principal.user_id,
            email=oauth_principal.email,
            role=oauth_principal.role,
            company_id=oauth_principal.company_id,
            scopes=frozenset(oauth_principal.scopes or ()),
            client_id=getattr(oauth_principal, "client_id", None),
        )

    return principal
