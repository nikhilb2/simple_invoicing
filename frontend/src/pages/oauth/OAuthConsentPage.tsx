import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Check, Globe, ShieldAlert, ShieldCheck } from 'lucide-react';
import { getApiErrorMessage } from '../../api/client';
import {
  fetchAuthorizationRequest,
  isExpiredAuthorizationRequest,
  submitAuthorizationDecision,
} from '../../features/oauth/api';
import { describeScope, isSensitiveScope } from '../../features/oauth/types';

/**
 * The one screen a user sees from *outside* this app.
 *
 * Claude or ChatGPT sends them here mid-flow, so it deliberately renders
 * standalone — no sidebar, no dashboard chrome to click away into — while
 * keeping the app's own brand mark, palette and card shapes, because the whole
 * value of a consent screen is the user recognising whose password they just
 * typed and whose data they are about to hand over.
 *
 * Two things it must get right:
 *
 *   - **The host, not the name.** `client_name` is whatever string the client
 *     put in its RFC 7591 registration; nobody verified it. `redirect_uri_host`
 *     is where the authorization code is actually delivered, so that is the
 *     line set in bold. A client calling itself "Claude" while redirecting to
 *     `codes.evil.example` has to look wrong here or the screen is theatre.
 *   - **One company.** The grant is bound to exactly one company at consent
 *     time and cannot be widened later, so the picker is a required part of
 *     the decision rather than a preference tucked away afterwards.
 */

/**
 * The backend builds `redirect_to` from the client's registered redirect_uri,
 * so it is legitimately cross-origin and cannot be same-origin checked. It can
 * still be required to be a real http(s) URL: assigning a `javascript:` URL
 * would execute in this app's origin, which no redirect ever needs to do.
 */
function isAssignableRedirect(value: string): boolean {
  try {
    const url = new URL(value, window.location.origin);
    return url.protocol === 'https:' || url.protocol === 'http:';
  } catch {
    return false;
  }
}

function ConsentShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="login-page">
      <div className="oauth-consent">
        <div className="oauth-consent__brand">
          <span aria-hidden="true">⚡</span>
          <span>Simple Invoicing</span>
        </div>
        {children}
      </div>
    </div>
  );
}

export default function OAuthConsentPage() {
  const [searchParams] = useSearchParams();
  const requestId = searchParams.get('request_id') ?? '';

  const [companyId, setCompanyId] = useState<string>('');
  const [decisionError, setDecisionError] = useState('');
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    document.title = 'Authorize access | Simple Invoicing';
  }, []);

  const requestQuery = useQuery({
    queryKey: ['oauth-authorize-request', requestId],
    queryFn: () => fetchAuthorizationRequest(requestId),
    enabled: requestId.length > 0,
    // A parked request is single-use and expires in ten minutes; refetching a
    // spent one only replaces the screen with an error the user cannot act on.
    retry: (failureCount, error) => !isExpiredAuthorizationRequest(error) && failureCount < 1,
    staleTime: Infinity,
    gcTime: 0,
  });

  const request = requestQuery.data ?? null;
  const companies = useMemo(() => request?.companies ?? [], [request]);

  // Pre-select as soon as there is something to select. A single company still
  // renders the picker, read-only, so the binding is never invisible.
  useEffect(() => {
    if (companyId === '' && companies.length > 0) {
      setCompanyId(String(companies[0].id));
    }
  }, [companies, companyId]);

  const decision = useMutation({
    mutationFn: (approve: boolean) =>
      submitAuthorizationDecision({ requestId, approve, companyId: Number(companyId) }),
    onSuccess: (data) => {
      if (!isAssignableRedirect(data.redirect_to)) {
        setDecisionError('The application sent back an address this browser will not open. Nothing was shared.');
        return;
      }
      // Held true for the rest of this document's life: the navigation is
      // already committed, and re-enabling the buttons would only invite a
      // second decision against a request that has now been consumed.
      setLeaving(true);
      window.location.assign(data.redirect_to);
    },
    onError: (error) => {
      setDecisionError(
        isExpiredAuthorizationRequest(error)
          ? 'This authorization request has expired. Start again from the app you were connecting.'
          : getApiErrorMessage(error, 'Unable to complete this authorization. Nothing was shared.'),
      );
    },
  });

  if (!requestId) {
    return (
      <ConsentShell>
        <ExpiredState
          title="Nothing to authorize"
          body="This page opens from an app asking to connect to your Simple Invoicing account, and it was opened without a request. Start again from that app."
        />
      </ConsentShell>
    );
  }

  if (requestQuery.isLoading) {
    return (
      <ConsentShell>
        <div className="empty-state">Loading authorization request…</div>
      </ConsentShell>
    );
  }

  if (requestQuery.error && isExpiredAuthorizationRequest(requestQuery.error)) {
    return (
      <ConsentShell>
        <ExpiredState
          title="This authorization request expired"
          body="Authorization requests are good for a few minutes and can only be used once. Start again from the app you were connecting, and you will be sent back here."
        />
      </ConsentShell>
    );
  }

  if (requestQuery.error || !request) {
    return (
      <ConsentShell>
        <div className="oauth-consent__card stack">
          <div>
            <p className="eyebrow">Authorization</p>
            <h1 className="page-title">Couldn't load this request</h1>
            <p className="section-copy">
              {getApiErrorMessage(requestQuery.error, 'The server could not be reached.')} Nothing has been shared.
            </p>
          </div>
          <div className="button-row">
            <button type="button" className="button button--primary" onClick={() => void requestQuery.refetch()}>
              Try again
            </button>
          </div>
        </div>
      </ConsentShell>
    );
  }

  const busy = decision.isPending || leaving;
  const canDecide = companyId !== '' && !busy;

  return (
    <ConsentShell>
      <div className="oauth-consent__card stack">
        <div>
          <p className="eyebrow">Authorization request</p>
          <h1 className="page-title" style={{ marginBottom: '8px' }}>
            {request.client_name || 'An application'} wants access to your account
          </h1>
          <p className="section-copy">
            Approving sends this application a key to your Simple Invoicing data. You can revoke it at any
            time from Settings → Connected apps.
          </p>
        </div>

        {/* The identity that is actually verifiable, given its own block so it
            is not read as a subtitle of the self-asserted name above. */}
        <div className="oauth-consent__host">
          <Globe size={18} aria-hidden="true" />
          <div>
            <p className="eyebrow">Codes will be sent to</p>
            <strong className="oauth-consent__host-value">{request.redirect_uri_host}</strong>
            {request.client_uri_host && request.client_uri_host !== request.redirect_uri_host ? (
              <p className="muted-text" style={{ margin: '4px 0 0' }}>
                Registered by {request.client_uri_host}
              </p>
            ) : null}
            <p className="muted-text" style={{ margin: '6px 0 0' }}>
              The name above is chosen by the application itself. If you do not recognise this address, deny.
            </p>
          </div>
        </div>

        <div>
          <p className="eyebrow" style={{ marginBottom: '8px' }}>It will be able to</p>
          <ul className="oauth-consent__scopes">
            {request.scopes.length === 0 ? (
              <li className="muted-text">No permissions requested.</li>
            ) : (
              request.scopes.map((entry) => (
                <li key={entry.scope} className="oauth-consent__scope">
                  {isSensitiveScope(entry.scope) ? (
                    <ShieldAlert size={16} aria-hidden="true" className="oauth-consent__scope-icon--warn" />
                  ) : (
                    <Check size={16} aria-hidden="true" />
                  )}
                  <span>
                    {describeScope(entry.scope, entry.description)}
                    <code className="oauth-consent__scope-code">{entry.scope}</code>
                  </span>
                </li>
              ))
            )}
          </ul>
        </div>

        <div className="field field--full">
          <label htmlFor="oauth-company">Company this access is limited to</label>
          <select
            id="oauth-company"
            className="select"
            value={companyId}
            onChange={(event) => setCompanyId(event.target.value)}
            disabled={busy || companies.length === 0}
          >
            {companies.length === 0 ? <option value="">No companies available</option> : null}
            {companies.map((company) => (
              <option key={company.id} value={company.id}>
                {company.name || `Company #${company.id}`}
              </option>
            ))}
          </select>
          <p className="muted-text" style={{ marginTop: '6px' }}>
            The connection is bound to this company only, and cannot reach the others later.
          </p>
        </div>

        {companies.length === 0 ? (
          <p className="field-warning">
            This account has no company to grant access to. Create one first, then start again from the
            application.
          </p>
        ) : null}

        {decisionError ? <p className="field-warning">{decisionError}</p> : null}

        <div className="button-row" style={{ justifyContent: 'flex-end' }}>
          <button
            type="button"
            className="button button--ghost"
            onClick={() => { setDecisionError(''); decision.mutate(false); }}
            disabled={busy}
          >
            Deny
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => { setDecisionError(''); decision.mutate(true); }}
            disabled={!canDecide}
          >
            <ShieldCheck size={16} aria-hidden="true" />
            {busy ? 'Working…' : 'Approve access'}
          </button>
        </div>
      </div>
    </ConsentShell>
  );
}

function ExpiredState({ title, body }: { title: string; body: string }) {
  return (
    <div className="oauth-consent__card stack">
      <div>
        <p className="eyebrow">Authorization</p>
        <h1 className="page-title">{title}</h1>
        <p className="section-copy">{body}</p>
      </div>
      <p className="muted-text">No access was granted, and nothing was shared.</p>
    </div>
  );
}
