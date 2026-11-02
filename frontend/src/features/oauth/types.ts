/**
 * The OAuth 2.1 authorization server's browser-facing surface.
 *
 * Only three of its endpoints are ours: the consent screen reads a parked
 * authorization request and posts a decision, and Settings lists and revokes
 * the grants that came out of them. Everything else — /authorize, /token,
 * /register, /revoke — is machine-to-machine and never touches this app.
 */

/** One permission the client is asking for, described by the server. */
export type OAuthScopeRequest = {
  scope: string;
  /** Plain-language copy from the backend. Falls back to SCOPE_LABELS. */
  description?: string | null;
};

/** A company the consenting user may bind the grant to. */
export type OAuthConsentCompany = {
  id: number;
  name: string;
};

/**
 * What the consent screen renders.
 *
 * `client_name` is self-asserted at registration by whoever registered the
 * client, so it is a label and not an identity. `redirect_uri_host` is where
 * the authorization code will actually be sent — that is the field a user can
 * make a trust decision on, and the screen leads with it.
 */
export type OAuthAuthorizationRequest = {
  client_name: string;
  client_uri_host?: string | null;
  redirect_uri_host: string;
  scopes: OAuthScopeRequest[];
  companies: OAuthConsentCompany[];
};

export type OAuthDecisionRequest = {
  request_id: string;
  approve: boolean;
  company_id: number;
};

/** Approve and deny both come back this way; deny carries `error=access_denied`. */
export type OAuthDecisionResponse = {
  redirect_to: string;
};

/** An active grant, as Settings → Connected apps lists it. */
export type OAuthGrant = {
  client_id: string;
  client_name: string;
  scopes: string[];
  company_name: string | null;
  created_at: string;
  last_used_at: string | null;
};

/**
 * Plain language for each scope, for the places the server sends no copy —
 * the grants list, and a consent request whose `description` is empty.
 */
export const SCOPE_LABELS: Record<string, string> = {
  'invoicing:read':
    'Read your invoices, ledgers, stock, payments and reports',
  'invoicing:write':
    'Create and change records — invoices, ledgers, products and payments',
  'invoicing:admin':
    'Manage company settings, users, invoice series and email configuration',
  'invoicing:send_email':
    'Send email to your customers from this company',
  offline_access:
    'Stay connected without asking you to sign in again',
};

export function describeScope(scope: string, description?: string | null): string {
  return description?.trim() || SCOPE_LABELS[scope] || scope;
}

/** The scopes worth a second look before approving. */
export function isSensitiveScope(scope: string): boolean {
  return scope === 'invoicing:write' || scope === 'invoicing:admin' || scope === 'invoicing:send_email';
}
