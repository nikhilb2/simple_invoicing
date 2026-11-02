"""Protocol constants and response budgets for the MCP server.

Everything deployment-tunable lives in :mod:`src.core.config`; this module holds
the values that are part of the protocol or of the response-shaping contract and
therefore should not drift per environment.
"""

from __future__ import annotations

# --- protocol -------------------------------------------------------------
# Newest first. `initialize` echoes the client's version when we speak it, and
# otherwise falls back to LATEST (the spec's "offer what you do support" rule).
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2026-07-28",
    "2025-11-25",
    "2025-06-18",
)
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
# Clients that omit MCP-Protocol-Version on a plain POST are, per spec, assumed
# to speak the revision before the header existed.
FALLBACK_PROTOCOL_VERSION = "2025-06-18"

SERVER_NAME = "simple-invoicing"
SERVER_TITLE = "Simple Invoicing"
SERVER_VERSION = "1.0.0"

# --- scopes ---------------------------------------------------------------
SCOPE_READ = "invoicing:read"
SCOPE_WRITE = "invoicing:write"
SCOPE_ADMIN = "invoicing:admin"
SCOPE_SEND_EMAIL = "invoicing:send_email"

ALL_SCOPES = (SCOPE_READ, SCOPE_WRITE, SCOPE_ADMIN, SCOPE_SEND_EMAIL)

# --- response budgets -----------------------------------------------------
# A 500-row list would eat the model's whole context, so page_size is clamped in
# the *arguments* before dispatch (the API itself allows up to 500).
MAX_PAGE_SIZE = 50
# Serialised-JSON budget for one tool result, before item-level truncation.
MAX_RESPONSE_BYTES = 40_000
# Hard ceiling applied last, after every other strategy has run.
HARD_RESPONSE_BYTES = 60_000
# Single strings (the company profile carries a base64 logo) are clamped first.
MAX_STRING_CHARS = 2_000
# CSV exports come back as text, not as a base64 blob.
MAX_CSV_ROWS = 200
MAX_CSV_BYTES = 30_000
# Binary bodies (PDFs) are never base64'd into the context.
BINARY_CONTENT_TYPES = ("application/pdf", "application/octet-stream", "application/zip")

# Concurrency cap for `search`'s fan-out across corpora.
#
# Set to 1 — i.e. serialised — on purpose. Each fanned-out call re-enters the app
# and runs a sync handler in the AnyIO threadpool, so N concurrent corpus queries
# means N threads touching the database at once. Against a pool that is really a
# single shared DBAPI connection (pytest's StaticPool SQLite, and any deployment
# pinned to one connection) that crashes the sqlite3 driver outright rather than
# raising. Five small in-process list queries are cheap in sequence, so the
# parallelism was not worth a failure mode that segfaults instead of erroring.
# Raise this only alongside a per-fan-out connection guarantee.
SEARCH_FANOUT_LIMIT = 1
SEARCH_DEFAULT_LIMIT = 10
SEARCH_MAX_LIMIT = 25

# Internal dispatch token TTL. Sixty seconds, not the 60-minute default: the
# token exists only for the duration of one in-process call.
INTERNAL_TOKEN_TTL_SECONDS = 60

# The in-process ASGI base URL. Never resolved over the network.
INTERNAL_BASE_URL = "http://mcp.internal"

# Audit breadcrumb header. `get_active_company` keys off this to avoid
# persisting active_company_id during a tool call.
MCP_TOOL_HEADER = "X-MCP-Tool"

PROFILE_CORE = "core"
PROFILE_ALL = "all"
VALID_PROFILES = (PROFILE_CORE, PROFILE_ALL)
