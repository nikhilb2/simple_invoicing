import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, KeyRound, Plug, Unplug } from 'lucide-react';
import { getApiErrorMessage } from '../../api/client';
import ConfirmDialog from '../../components/ConfirmDialog';
import StatusToasts from '../../components/StatusToasts';
import {
  disconnectMarketplace,
  fetchMarketplaceMeta,
  registerConnection,
  rotateCredential,
  updateConnection,
} from '../../features/marketplace/api';
import { marketplaceQueryKeys } from '../../features/marketplace/queryKeys';
import { useMarketplaceConnection } from '../../features/marketplace/useMarketplaceSync';
import type { MarketplaceConnectionStatus } from '../../features/marketplace/types';
import { fetchCompanyProfile } from '../../features/invoices/api';
import { invoiceQueryKeys } from '../../features/invoices/queryKeys';
import { formatDateTime, formatRelativeTime, hoursSince } from './components/format';

/** Beyond this, an instance that is actively selling is almost certainly missing
 *  events — the frontend poll only runs while somebody has the app open. */
const STALE_SYNC_HOURS = 24;

const STATUS_COPY: Record<MarketplaceConnectionStatus, { label: string; detail: string }> = {
  unregistered: {
    label: 'Not connected',
    detail: 'Paste a marketplace URL below and register this company to start trading.',
  },
  pending_approval: {
    label: 'Awaiting operator approval',
    detail:
      'Registration succeeded. A marketplace operator must approve this company before it can publish listings or place orders. This app picks the approval up automatically on its next sync — do not register again.',
  },
  connected: {
    label: 'Connected',
    detail: 'This company can browse, publish listings and trade on the marketplace.',
  },
  unauthorized: {
    label: 'Credential rejected',
    detail:
      'The marketplace no longer accepts this credential. Syncing has stopped. Rotate the key, or disconnect and register again.',
  },
  suspended: {
    label: 'Suspended by the operator',
    detail: 'Trading is blocked until the operator lifts the suspension. Contact the marketplace operator.',
  },
  disconnected: {
    label: 'Disconnected',
    detail: 'This company was disconnected from the marketplace. Register again to resume trading.',
  },
};

export default function MarketplaceSettingsPage() {
  const queryClient = useQueryClient();
  const connectionQuery = useMarketplaceConnection();
  const companyQuery = useQuery({ queryKey: invoiceQueryKeys.company, queryFn: fetchCompanyProfile });

  const [baseUrl, setBaseUrl] = useState('');
  const [probedUrl, setProbedUrl] = useState('');
  const [form, setForm] = useState({ contactEmail: '', contactPhone: '' });
  const [autoAccept, setAutoAccept] = useState(true);
  const [autoAcceptCap, setAutoAcceptCap] = useState('');
  const [autoPost, setAutoPost] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const connection = connectionQuery.data;
  const status = connection?.status ?? 'unregistered';
  const registered = status !== 'unregistered' && status !== 'disconnected';

  // Seed the editable settings once per connection identity. The sync poll
  // refetches this query every 60 s, and re-seeding on every response would
  // wipe out whatever the user was in the middle of typing.
  const seededFor = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (!connection || seededFor.current === connection.seller_id) return;
    seededFor.current = connection.seller_id;
    setAutoAccept(connection.auto_accept);
    setAutoAcceptCap(connection.auto_accept_max_amount ?? '');
    setAutoPost(connection.auto_post);
    if (connection.base_url) setBaseUrl(connection.base_url);
  }, [connection]);

  useEffect(() => {
    if (!companyQuery.data) return;
    setForm((current) => ({
      ...current,
      contactEmail: current.contactEmail || companyQuery.data?.email || '',
      contactPhone: current.contactPhone || companyQuery.data?.phone_number || '',
    }));
  }, [companyQuery.data]);

  const metaQuery = useQuery({
    queryKey: marketplaceQueryKeys.meta(probedUrl),
    queryFn: () => fetchMarketplaceMeta(probedUrl),
    enabled: probedUrl !== '',
    retry: false,
  });

  const registerMutation = useMutation({
    mutationFn: () =>
      registerConnection({
        base_url: baseUrl.trim(),
        legal_name: companyQuery.data?.name,
        contact_email: form.contactEmail.trim(),
        contact_phone: form.contactPhone.trim() || undefined,
      }),
    onSuccess: (result) => {
      setSuccess(
        result.status === 'pending_approval'
          ? 'Registered. An operator must approve this company before it can trade.'
          : 'Registered with the marketplace.',
      );
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Registration failed')),
  });

  const settingsMutation = useMutation({
    mutationFn: () =>
      updateConnection({
        auto_accept: autoAccept,
        auto_accept_max_amount: autoAcceptCap.trim() || null,
        auto_post: autoPost,
      }),
    onSuccess: () => {
      setSuccess('Marketplace settings saved.');
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to save these settings')),
  });

  const rotateMutation = useMutation({
    mutationFn: rotateCredential,
    onSuccess: () => {
      setSuccess('Credential rotated. The previous key stops working within the hour.');
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to rotate the credential')),
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectMarketplace,
    onSuccess: () => {
      setSuccess('Disconnected from the marketplace.');
      setConfirmDisconnect(false);
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => {
      setError(getApiErrorMessage(err, 'Unable to disconnect'));
      setConfirmDisconnect(false);
    },
  });

  const syncAgeHours = hoursSince(connection?.last_sync_at);
  const syncIsStale = registered && (syncAgeHours === null || syncAgeHours > STALE_SYNC_HOURS);
  const statusCopy = STATUS_COPY[status];

  return (
    <div className="marketplace-page stack">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page-title">Marketplace</h1>
          <p className="section-copy">
            Connect this company to a marketplace so it can trade surplus stock with other businesses
            running this app.
          </p>
        </div>
      </section>

      <section className={`panel stack marketplace-status marketplace-status--${status}`}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Connection status</p>
            <h2 className="nav-panel__title">{statusCopy.label}</h2>
          </div>
          {connection?.base_url && <span className="status-chip">{connection.base_url}</span>}
        </div>
        <p className="section-copy">{statusCopy.detail}</p>

        {registered && (
          <dl className="marketplace-summary">
            <div>
              <dt>Seller ID</dt>
              <dd>{connection?.seller_id || '—'}</dd>
            </div>
            <div>
              <dt>GSTIN</dt>
              <dd>{connection?.gstin || '—'}</dd>
            </div>
            <div>
              <dt>Credential</dt>
              <dd>{connection?.credential_prefix ? `${connection.credential_prefix}…` : '—'}</dd>
            </div>
            <div>
              <dt>Last sync</dt>
              <dd>
                {formatRelativeTime(connection?.last_sync_at)}
                <span className="marketplace-summary__hint">{formatDateTime(connection?.last_sync_at)}</span>
              </dd>
            </div>
          </dl>
        )}

        {connection?.last_sync_error && (
          <p className="marketplace-note marketplace-note--error">
            Last sync failed: {connection.last_sync_error}
          </p>
        )}

        {syncIsStale && (
          <div className="marketplace-alert" role="alert">
            <AlertTriangle size={18} />
            <div>
              <strong>This connection has not synced in over {STALE_SYNC_HOURS} hours.</strong>
              <p>
                Orders only reach this instance when something drains the event feed. The in-app poll
                runs while somebody has the app open — which is not enough if you actively sell.
                Schedule <code>POST /api/marketplace/sync-all</code> from cron (every 5 minutes,
                authenticated with an <code>si_</code> API key) so orders are not missed and do not
                expire unanswered.
              </p>
            </div>
          </div>
        )}
      </section>

      {!registered && (
        <section className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Step 1</p>
              <h2 className="nav-panel__title">Point at a marketplace</h2>
            </div>
          </div>

          <div className="field">
            <label htmlFor="marketplace-base-url">Marketplace URL</label>
            <input
              id="marketplace-base-url"
              className="input"
              type="url"
              placeholder="https://marketplace.example.com"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </div>

          <div className="button-row">
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setProbedUrl(baseUrl.trim())}
              disabled={!baseUrl.trim() || metaQuery.isFetching}
            >
              <Plug size={16} />
              {metaQuery.isFetching ? 'Testing…' : 'Test connection'}
            </button>
          </div>

          {metaQuery.error && (
            <p className="marketplace-note marketplace-note--error">
              {getApiErrorMessage(metaQuery.error, 'Could not reach that marketplace')}
            </p>
          )}

          {metaQuery.data && (
            <div className="marketplace-meta">
              <h3>{metaQuery.data.marketplace_name}</h3>
              <ul>
                <li>
                  Registration is {metaQuery.data.registration_open ? 'open' : 'closed'}.
                </li>
                <li>
                  {metaQuery.data.requires_approval
                    ? 'New sellers are approved by an operator before they can trade.'
                    : 'New sellers can trade immediately.'}
                </li>
                {metaQuery.data.order_ttl_hours != null && (
                  <li>Unanswered orders expire after {metaQuery.data.order_ttl_hours} hours.</li>
                )}
                {metaQuery.data.min_client_version && (
                  <li>Minimum client version {metaQuery.data.min_client_version}.</li>
                )}
                {metaQuery.data.terms_url && (
                  <li>
                    <a href={metaQuery.data.terms_url} target="_blank" rel="noreferrer">
                      Read the marketplace terms
                    </a>
                  </li>
                )}
              </ul>
            </div>
          )}
        </section>
      )}

      {!registered && metaQuery.data && (
        <section className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Step 2</p>
              <h2 className="nav-panel__title">Register this company</h2>
            </div>
          </div>

          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              registerMutation.mutate();
            }}
          >
            <div className="field-grid">
              <div className="field">
                <label htmlFor="marketplace-legal-name">Legal name</label>
                <input
                  id="marketplace-legal-name"
                  className="input"
                  type="text"
                  value={companyQuery.data?.name ?? ''}
                  readOnly
                />
              </div>
              <div className="field">
                <label htmlFor="marketplace-gstin">GSTIN</label>
                <input
                  id="marketplace-gstin"
                  className="input"
                  type="text"
                  value={companyQuery.data?.gst ?? ''}
                  readOnly
                />
              </div>
              <div className="field">
                <label htmlFor="marketplace-contact-email">Contact email</label>
                <input
                  id="marketplace-contact-email"
                  className="input"
                  type="email"
                  value={form.contactEmail}
                  onChange={(event) => setForm({ ...form, contactEmail: event.target.value })}
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="marketplace-contact-phone">Contact phone</label>
                <input
                  id="marketplace-contact-phone"
                  className="input"
                  type="tel"
                  value={form.contactPhone}
                  onChange={(event) => setForm({ ...form, contactPhone: event.target.value })}
                />
              </div>
            </div>

            <p className="marketplace-note">
              Legal name and GSTIN come from this company's profile and identify you to every other
              instance on the marketplace. Change them under Company if they are wrong — a GSTIN can
              only be claimed once.
            </p>

            <div className="button-row">
              <button
                type="submit"
                className="button button--primary"
                disabled={registerMutation.isPending || !form.contactEmail.trim()}
              >
                {registerMutation.isPending ? 'Registering…' : 'Register with this marketplace'}
              </button>
            </div>
          </form>
        </section>
      )}

      {registered && (
        <section className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Automation</p>
              <h2 className="nav-panel__title">Order handling</h2>
            </div>
          </div>

          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              settingsMutation.mutate();
            }}
          >
            <label className="marketplace-checkbox">
              <input
                type="checkbox"
                checked={autoAccept}
                onChange={(event) => setAutoAccept(event.target.checked)}
              />
              <span>
                Accept incoming orders automatically when the stock is there. Orders that fail the
                stock check are rejected, never silently accepted.
              </span>
            </label>

            <div className="field">
              <label htmlFor="marketplace-auto-accept-cap">Auto-accept only below</label>
              <input
                id="marketplace-auto-accept-cap"
                className="input"
                type="text"
                inputMode="decimal"
                placeholder="No cap"
                value={autoAcceptCap}
                onChange={(event) => setAutoAcceptCap(event.target.value)}
                disabled={!autoAccept}
              />
              <p className="marketplace-note">
                Orders above this total wait for a manual Accept on the Orders page. Leave blank for
                no cap.
              </p>
            </div>

            <label className="marketplace-checkbox">
              <input
                type="checkbox"
                checked={autoPost}
                onChange={(event) => setAutoPost(event.target.checked)}
              />
              <span>
                Post invoices automatically. A confirmed order writes a sales invoice and decrements
                stock on the seller, and a purchase invoice and increments stock on the buyer, with
                no human review.
              </span>
            </label>

            <div className="button-row">
              <button type="submit" className="button button--primary" disabled={settingsMutation.isPending}>
                {settingsMutation.isPending ? 'Saving…' : 'Save settings'}
              </button>
            </div>
          </form>
        </section>
      )}

      {registered && (
        <section className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Credential</p>
              <h2 className="nav-panel__title">Danger zone</h2>
            </div>
          </div>

          <p className="section-copy">
            The credential is stored encrypted on this instance and is never sent to the browser.
            Rotate it if you suspect it was copied; the old key keeps working for about an hour so a
            running cron does not break mid-drain.
          </p>

          <div className="button-row">
            <button
              type="button"
              className="button button--secondary"
              onClick={() => rotateMutation.mutate()}
              disabled={rotateMutation.isPending}
            >
              <KeyRound size={16} />
              {rotateMutation.isPending ? 'Rotating…' : 'Rotate credential'}
            </button>
            <button
              type="button"
              className="button button--danger"
              onClick={() => setConfirmDisconnect(true)}
              disabled={disconnectMutation.isPending}
            >
              <Unplug size={16} />
              Disconnect
            </button>
          </div>
        </section>
      )}

      {confirmDisconnect && (
        <ConfirmDialog
          title="Disconnect from the marketplace"
          message="This withdraws every listing you published and cancels your open orders on the marketplace. Invoices already posted stay in your books. Reconnecting means registering again."
          confirmText="Disconnect"
          danger
          onConfirm={() => disconnectMutation.mutate()}
          onCancel={() => setConfirmDisconnect(false)}
        />
      )}

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />
    </div>
  );
}
