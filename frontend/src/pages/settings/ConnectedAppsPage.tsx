import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plug, Trash2 } from 'lucide-react';
import { getApiErrorMessage } from '../../api/client';
import { fetchGrants, revokeGrant } from '../../features/oauth/api';
import { SCOPE_LABELS, type OAuthGrant } from '../../features/oauth/types';
import StatusToasts from '../../components/StatusToasts';
import ConfirmDialog from '../../components/ConfirmDialog';

/**
 * The other end of the consent screen: every MCP client this user approved,
 * and the button that cuts one off.
 *
 * Per-user rather than admin-only, unlike the API keys page beside it. An API
 * key is instance infrastructure; a grant is one person's own connection,
 * carrying their identity and their role, and only they can meaningfully judge
 * whether it should still exist.
 */

const GRANTS_QUERY_KEY = ['oauth-grants'];

function formatMoment(value: string | null | undefined, fallback: string): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/** Scope chips, labelled in plain language with the raw scope on hover. */
function ScopeChips({ scopes }: { scopes: string[] }) {
  if (scopes.length === 0) {
    return <span className="muted-text">No scopes</span>;
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
      {scopes.map((scope) => (
        <span key={scope} className="status-chip status-chip--breakable" title={SCOPE_LABELS[scope] ?? scope}>
          {scope.replace(/^invoicing:/, '')}
        </span>
      ))}
    </div>
  );
}

export default function ConnectedAppsPage() {
  const queryClient = useQueryClient();
  const [revokeTarget, setRevokeTarget] = useState<OAuthGrant | null>(null);
  const [toast, setToast] = useState<{ kind: 'success' | 'error'; message: string } | null>(null);

  const grantsQuery = useQuery({
    queryKey: GRANTS_QUERY_KEY,
    queryFn: fetchGrants,
  });

  const revokeMutation = useMutation({
    mutationFn: (grant: OAuthGrant) => revokeGrant(grant.client_id),
    onSuccess: (_data, grant) => {
      setToast({
        kind: 'success',
        message: `${grant.client_name || 'The application'} can no longer reach your data.`,
      });
      void queryClient.invalidateQueries({ queryKey: GRANTS_QUERY_KEY });
    },
    onError: (error) => {
      setToast({ kind: 'error', message: getApiErrorMessage(error, 'Failed to revoke access') });
    },
    onSettled: () => setRevokeTarget(null),
  });

  const grants = grantsQuery.data ?? [];

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page-title">Connected Apps</h1>
          <p className="section-copy">
            Assistants and other apps you have given access to, through the connector sign-in flow. Revoking
            one takes effect on its next request.
          </p>
        </div>
      </section>

      {grantsQuery.isLoading ? (
        <p style={{ opacity: 0.5 }}>Loading…</p>
      ) : grantsQuery.error ? (
        <div className="empty-state">
          <p>{getApiErrorMessage(grantsQuery.error, 'Unable to load connected apps.')}</p>
          <div className="button-row" style={{ justifyContent: 'center', marginTop: '16px' }}>
            <button type="button" className="button button--primary" onClick={() => void grantsQuery.refetch()}>
              Try again
            </button>
          </div>
        </div>
      ) : grants.length === 0 ? (
        <div className="empty-state">
          <Plug size={32} opacity={0.3} />
          <p>
            Nothing is connected. Add this workspace as a connector in Claude, ChatGPT or another MCP client,
            and the access you approve will be listed here.
          </p>
        </div>
      ) : (
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th>Application</th>
                <th>Company</th>
                <th>Access</th>
                <th>Connected</th>
                <th>Last used</th>
                <th style={{ width: '48px' }} />
              </tr>
            </thead>
            <tbody>
              {grants.map((grant) => (
                <tr key={grant.client_id}>
                  <td>
                    <strong>{grant.client_name || 'Unnamed application'}</strong>
                    {/* The name is self-asserted at registration; the client_id
                        is what the server actually knows this app by. */}
                    <span className="table-subtext" style={{ display: 'block', fontFamily: 'monospace', fontSize: '0.74rem' }}>
                      {grant.client_id}
                    </span>
                  </td>
                  <td>{grant.company_name || <span className="muted-text">—</span>}</td>
                  <td><ScopeChips scopes={grant.scopes} /></td>
                  <td>{formatMoment(grant.created_at, '—')}</td>
                  <td>{formatMoment(grant.last_used_at, 'Never')}</td>
                  <td>
                    <button
                      className="button button--ghost button--icon"
                      title="Revoke access"
                      aria-label={`Revoke access for ${grant.client_name || grant.client_id}`}
                      onClick={() => setRevokeTarget(grant)}
                      disabled={revokeMutation.isPending}
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {revokeTarget && (
        <ConfirmDialog
          title="Revoke access"
          message={`Revoke access for "${revokeTarget.client_name || revokeTarget.client_id}"? It will stop working immediately, and reconnecting means approving it again.`}
          confirmText={revokeMutation.isPending ? 'Revoking…' : 'Revoke'}
          onConfirm={() => revokeMutation.mutate(revokeTarget)}
          onCancel={() => setRevokeTarget(null)}
          danger
        />
      )}

      {toast && toast.kind === 'error' && (
        <StatusToasts error={toast.message} onClearError={() => setToast(null)} onClearSuccess={() => {}} />
      )}
      {toast && toast.kind === 'success' && (
        <StatusToasts success={toast.message} onClearError={() => {}} onClearSuccess={() => setToast(null)} />
      )}
    </div>
  );
}
