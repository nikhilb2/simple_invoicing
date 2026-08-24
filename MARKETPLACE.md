# Marketplace API Contract — v1

This document is the contract between **self-hosted invoicing instances** and the
**central marketplace server**. It is the source of truth for both sides and is kept
byte-identical in `simple_marketplace/MARKETPLACE.md` and
`respawn-invoicing/MARKETPLACE.md`. Change it in one place, copy to the other.

---

## 0. Model

- Each **`CompanyProfile`** on an instance registers separately as a **seller**, identified
  by GSTIN. A seller is both a seller and a buyer — there is no separate buyer entity.
- **No money ever flows through the marketplace.** It is a discovery and order-matching
  service. Settlement happens offline between the two businesses.
- The **central server can never reach an instance.** Instances are self-hosted, often on
  localhost or behind NAT. All delivery is **pull-based**: the instance drains a
  cursor-ordered event feed.
- **Stock authority lives on the seller's instance.** The quantity the marketplace shows is
  an advisory snapshot the seller republishes; it is stale by construction.

## 1. Transport

- Base URL: `{marketplace_base_url}/v1`. All JSON, UTF-8.
- All timestamps are RFC 3339 UTC strings: `2026-08-22T10:03:11Z`.
- **All money and quantity values are decimal strings, never JSON numbers.** `"125.00"`,
  not `125.0`. This is not a style preference — float round-tripping silently corrupts
  tax arithmetic.
- Error envelope, on every non-2xx:
  ```json
  { "error": "machine_code", "detail": "human readable", "request_id": "req_..." }
  ```
- `429` responses carry `Retry-After` in seconds.

### Headers

| Header | Direction | Notes |
|---|---|---|
| `Authorization: Bearer mk_live_<64 hex>` | instance → central | Required on everything except `/meta`, `/health`, `/sellers/register`. |
| `X-Marketplace-Client: respawn-invoicing/<version>` | instance → central | Required. Used for `min_client_version` enforcement. |
| `X-Marketplace-Instance: <uuid>` | instance → central | Stable per install. A mismatch against the registered value is logged — it means the credential was copied to another machine. |
| `Idempotency-Key: <uuid>` | instance → central | Required on `POST /orders`, `/orders/{id}/accept`, `/orders/{id}/posting`. The server returns the original response for a replayed key within 24 h. |

### Auth

The API key is issued **once**, at registration, and never shown again. The central server
stores it hashed with a plaintext prefix for display; the instance stores it Fernet-encrypted.
`POST /sellers/me/rotate-key` issues a replacement and keeps the old key valid for 60 minutes.

## 2. Seller lifecycle

```
    register
       │
       ▼
 pending_approval ──operator approves──▶ active ──operator suspends──▶ suspended
       │                                   │                              │
       └──operator rejects──▶ rejected     └──DELETE /sellers/me──▶ closed◀┘
```

Registration is **open** — anyone may call `POST /sellers/register` — but a new seller lands
in `pending_approval`. In that state every `/listings` and `/orders` call returns
`403 seller_not_approved`. Only `/meta`, `/health`, `/sellers/me` and `/events` work.

When an operator approves, the server emits `seller.status_changed` to that seller's feed, so
the instance flips to connected on its next sync **without the user re-registering**.

GSTIN ownership is **not verified in v1**. See §8.

## 3. Endpoints

### 3.1 Discovery

```http
GET /v1/health                                                    (no auth)
200 { "status": "ok" }
```

```http
GET /v1/meta                                                      (no auth)
200 {
  "marketplace_name": "Simple Marketplace",
  "min_client_version": "0.1.0",
  "terms_url": "https://.../terms",
  "registration_open": true,
  "requires_approval": true,
  "order_ttl_hours": 168,
  "event_retention_days": 90
}
```

`/meta` is what an instance's Settings page hits first, to validate a pasted base URL before
attempting registration.

### 3.2 Registration and profile

```http
POST /v1/sellers/register                                         (no auth)
{
  "gstin": "27ABCDE1234F1Z5",
  "legal_name": "Acme Traders Pvt Ltd",
  "address": "12 Industrial Estate, Pune",
  "state_code": "27",
  "contact_email": "ops@acme.example",
  "contact_phone": "+919000000000",
  "instance_id": "<uuid, stable per install>",
  "client_version": "0.1.0"
}
201 {
  "seller_id": "sel_9f3a...",
  "api_key": "mk_live_<64 hex>",          // shown ONCE, never retrievable
  "status": "pending_approval"
}
409 { "error": "gstin_already_claimed" }
422 { "error": "invalid_gstin" }
503 { "error": "registration_closed" }
```

```http
GET   /v1/sellers/me            → profile + status + listing_count + open_order_count
PATCH /v1/sellers/me            { legal_name?, address?, contact_email?, contact_phone? }
POST  /v1/sellers/me/rotate-key → { "api_key": "mk_live_..." }   old key valid 60 min
DELETE /v1/sellers/me           → 204   withdraws all listings, cancels open orders
```

### 3.3 Listings

`asking_price` is **per unit and tax-exclusive**. `gst_rate` is the seller's declared rate.
Both sides post invoices with `tax_inclusive=false` so the two documents agree to the paisa.

```http
POST /v1/listings                                                 (auth, active only)
{
  "title": "Bearing 6204-2RS",
  "description": "Surplus stock, unopened boxes",
  "asking_price": "125.00",
  "currency_code": "INR",
  "gst_rate": "18.00",
  "hsn_sac": "8482",
  "unit": "Pieces",
  "allow_decimal": false,
  "min_order_quantity": "10",
  "max_order_quantity": "500",
  "available_quantity": "400",
  "listing_type": "buy_now",
  "external_ref": "<the instance's local product id>"
}
201 { "listing_id": "lst_...", "status": "active", ... }
403 { "error": "seller_not_approved" }
```

```http
PATCH  /v1/listings/{listing_id}    any subset; the quantity refresh uses this
DELETE /v1/listings/{listing_id}    204, soft — status becomes "withdrawn"
GET    /v1/listings/mine            ?status=&page=&page_size=
GET    /v1/listings/{listing_id}
POST   /v1/listings/{listing_id}/report   { "reason": "...", "note": "..." }
```

Browse across all instances:

```http
GET /v1/listings?q=&hsn_sac=&gst_rate=&min_price=&max_price=&seller_state_code=
                &in_stock=true&exclude_own=true&sort=newest|price_asc|price_desc
                &cursor=&page_size=50                          (max 100)
200 {
  "items": [{
    "listing_id": "lst_...",
    "title": "...", "description": "...",
    "asking_price": "125.00", "currency_code": "INR",
    "gst_rate": "18.00", "hsn_sac": "8482", "unit": "Pieces", "allow_decimal": false,
    "min_order_quantity": "10", "max_order_quantity": "500",
    "available_quantity": "400",
    "available_quantity_as_of": "2026-08-22T09:51:00Z",
    "seller": {
      "seller_id": "sel_...", "legal_name": "...",
      "gstin": "27ABCDE1234F1Z5", "state_code": "27",
      "verified": false
    }
  }],
  "next_cursor": "...",
  "total_estimate": 1234
}
```

`available_quantity_as_of` exists so the browsing UI can say *"Seller reports 400 in stock
(as of 12 min ago)"*. Never present it as live.

### 3.4 Orders

```
 pending ──accept──▶ accepted ──posting──▶ posted
    │                    │
    ├──reject──▶ rejected│
    ├──cancel──▶ cancelled
    └──ttl─────▶ expired
```

```http
POST /v1/orders                          (auth: buyer, Idempotency-Key required)
{ "listing_id": "lst_...", "quantity": "10",
  "buyer_note": "...", "delivery_address": "..." }
201 {
  "order_id": "ord_...", "state": "pending",
  "expires_at": "2026-08-29T10:03:11Z",
  "unit_price": "125.00", "total_amount": "1250.00",
  "seller": { "seller_id", "legal_name", "gstin", "state_code", "address", "contact_phone" },
  "lines": [{ "line_no": 1, "listing_id": "lst_...", "title": "...",
              "quantity": "10", "unit": "Pieces", "unit_price": "125.00",
              "gst_rate": "18.00", "hsn_sac": "8482" }]
}
409 { "error": "insufficient_advertised_quantity", "available": "4" }
409 { "error": "listing_not_active" }
409 { "error": "cannot_order_own_listing" }
429 { "error": "open_order_limit_reached" }
```

Placing an order **soft-reserves** the quantity on the listing. This kills the common
two-buyers-in-the-same-second race. It is not a guarantee — the seller's instance holds the
real stock and may still reject.

```http
GET  /v1/orders?role=seller|buyer&state=&page=&page_size=
GET  /v1/orders/{order_id}

POST /v1/orders/{order_id}/accept        (auth: seller, Idempotency-Key)
{}  → 200 { "state": "accepted", "accepted_at": "..." }
    → 409 { "error": "invalid_state_transition", "state": "expired" }

POST /v1/orders/{order_id}/reject        (auth: seller)
{ "reason": "insufficient_stock" | "price_changed" | "cannot_ship"
           | "unknown_buyer" | "other",
  "note": "..." }
→ 200 { "state": "rejected" }            releases the reservation

POST /v1/orders/{order_id}/cancel        (auth: buyer, pending only)
→ 200 { "state": "cancelled" }
```

**The posting handshake.** The seller reports that its sales invoice is committed. This is
what unlocks the buyer's auto-post — the buyer must never create a purchase invoice off
`order.accepted` alone, or a failure on the seller side leaves an orphan document.

```http
POST /v1/orders/{order_id}/posting       (auth: seller, Idempotency-Key)
{
  "invoice_number": "INV-2026-27-000042",
  "invoice_date": "2026-08-22",
  "currency_code": "INR",
  "seller_gstin": "27ABCDE1234F1Z5",
  "taxable_amount": "1250.00",
  "tax_amount": "225.00",
  "total_amount": "1475.00",
  "lines": [{
    "line_no": 1, "listing_id": "lst_...", "title": "Bearing 6204-2RS",
    "quantity": "10", "unit": "Pieces", "unit_price": "125.00",
    "gst_rate": "18.00", "hsn_sac": "8482",
    "taxable_amount": "1250.00", "tax_amount": "225.00", "line_total": "1475.00"
  }]
}
→ 200 { "state": "posted" }

POST /v1/orders/{order_id}/buyer-posting (auth: buyer, optional — seller visibility only)
{ "invoice_number": "PUR-2026-27-000011", "invoice_date": "2026-08-22" }
→ 200
```

### 3.5 The event feed

The only delivery mechanism. Instances poll it; the server never pushes.

```http
GET /v1/events?since=<seq>&limit=200                              (auth)
200 {
  "events": [{
    "event_id": "evt_01J...",        // stable across redeliveries
    "seq": 10241,                     // strictly monotonic per subscriber
    "type": "order.created",
    "occurred_at": "2026-08-22T10:03:11Z",
    "order_id": "ord_...",
    "data": { ...full snapshot of the subject... }
  }],
  "next_since": 10241,
  "has_more": true,
  "retention_until_seq": 900
}
409 { "error": "cursor_too_old", "resync_from": 900 }
```

`retention_until_seq` is the **lowest seq still retained** for this subscriber (0 when the
feed has never been pruned).

`409 cursor_too_old` is returned only when the cursor has genuinely fallen behind pruning —
`retention_until_seq > 0 AND since + 1 < retention_until_seq`. Note the `+ 1`: a cursor is
the seq of the last event *already applied*, so a client sitting at `retention_until_seq - 1`
is asking for the earliest retained event and must be served, not rejected.
`resync_from` is `retention_until_seq - 1`, i.e. a cursor that resumes **at** the earliest
retained event rather than skipping past it.

On `cursor_too_old` the instance abandons its cursor, does a full reconcile via
`GET /v1/orders`, and then resumes from `resync_from`.

| Type | Delivered to | What the instance does |
|---|---|---|
| `order.created` | seller | Upsert the order as `pending`. |
| `order.cancelled` | seller | State transition only. |
| `order.expired` | both | State transition only. |
| `order.accepted` | buyer | State → `accepted`. **No posting yet.** |
| `order.rejected` | buyer | State → `rejected`, store the reason. |
| `order.posted` | buyer | Store the seller's invoice snapshot, then post the purchase invoice. |
| `order.buyer_posted` | seller | Informational; store the buyer's invoice number. |
| `listing.moderated` | owner | Listing → `rejected`/`paused`, store the reason. |
| `seller.status_changed` | self | Connection status: approved, suspended, closed. |

**Server invariants the client depends on:**

1. `seq` is **per-subscriber and monotonic**, assigned under a per-subscriber lock. Without
   this, the client's in-order application is meaningless.
2. `event_id` is **stable** — a redelivered event keeps its id. The client dedupes on it.
3. Events are retained **≥ 90 days**.

## 4. Idempotency

`POST /orders`, `/orders/{id}/accept` and `/orders/{id}/posting` require an
`Idempotency-Key`. The server stores `(seller_id, key) → (request_hash, response)` for 24 h.
A replay with the same key and the same body returns the stored response verbatim. A replay
with the same key and a **different** body returns `409 idempotency_key_reused`.

## 5. Rate limits

| Scope | Limit |
|---|---|
| `POST /sellers/register` | 5 / hour / IP |
| `POST /orders` | 60 / hour / seller, and 10 / day / (buyer, seller) pair |
| `GET /events` | 120 / hour / seller |
| Everything else | 600 / hour / seller |
| Listings per seller | 500 active |

## 6. Client obligations

A conforming instance **must**:

1. Apply events strictly in `seq` order and never advance its cursor past an unapplied event.
2. Dedupe on `event_id` with a unique constraint, not an in-memory set.
3. **Validate every `order.posted` payload against the order it already holds** — `listing_id`,
   `quantity`, `unit_price`, and the counterparty GSTIN must match. On any divergence, refuse
   to post and surface the failure. Without this check a compromised central server can inject
   a fabricated purchase invoice into any instance that placed an order.
4. Check real local stock before accepting; reject with `insufficient_stock` rather than
   accepting and failing to post.
5. Treat a missing or malformed counterparty GSTIN as a **permanent posting failure**, never
   as an intrastate supply.
6. Post both sides with `tax_inclusive=false` and `apply_round_off=false`.
7. Republish `available_quantity` when local stock drifts from what was last published.

## 7. Versioning

The path carries the major version (`/v1`). Additive changes — new optional request fields,
new response fields, new event types — ship without a version bump; clients must ignore
unknown fields and unknown event types (recording them as `ignored`, advancing the cursor).
Removals and semantic changes require `/v2`. `min_client_version` in `/meta` lets the operator
refuse dangerously old clients.

## 8. Trust posture — v1

**GSTIN ownership is not verified.** A registrant proves only that they know a well-formed,
unclaimed GSTIN. Guards that do exist:

- **Operator approval** before a seller can list or order. This is the load-bearing guard.
- GSTIN format **and check digit** validation.
- First-claim-wins uniqueness (`409 gstin_already_claimed`).
- Rate limits (§5) and the listing report/moderation queue.
- `X-Marketplace-Instance` mismatch logging, so a copied credential is detectable.

Instances **must** render an *unverified seller* badge wherever a counterparty is shown, with
copy to the effect of: *"Sellers are self-declared. Verify the counterparty independently
before shipping or paying."*
