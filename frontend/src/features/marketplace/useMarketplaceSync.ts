import { useCallback, useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchConnection, runSync } from './api';
import { marketplaceQueryKeys } from './queryKeys';
import type { MarketplaceConnectionStatus } from './types';

/**
 * Statuses in which draining the feed is worth attempting.
 *
 * `pending_approval` is included deliberately: the approval itself arrives as a
 * `seller.status_changed` event, so an instance that stopped polling while
 * pending would never learn it had been approved. `unauthorized`, `suspended`
 * and `disconnected` stop syncing — the settings page tells the user why.
 */
const SYNCABLE_STATUSES: MarketplaceConnectionStatus[] = ['connected', 'pending_approval'];

const SYNC_INTERVAL_MS = 60_000;

/** The shared connection query. Every marketplace page reads it through this
 *  hook so the poll gate and the pages hit one cache entry, not several. */
export function useMarketplaceConnection() {
  return useQuery({
    queryKey: marketplaceQueryKeys.connection(),
    queryFn: fetchConnection,
    // A missing connection or a company-less session is an ordinary outcome
    // here, not something to retry into.
    retry: false,
    staleTime: SYNC_INTERVAL_MS,
  });
}

/**
 * Whether this company can publish to a marketplace right now.
 *
 * `PublishToMarketplaceButton` gates itself, but a page that gives the action
 * its own table column has to know before it renders the header — otherwise an
 * unconnected company gets a permanently empty column.
 */
export function useCanPublishToMarketplace(): boolean {
  const { data } = useMarketplaceConnection();
  return data?.status === 'connected';
}

/**
 * Mounted once in Layout. This is the primary delivery path for marketplace
 * events — the central server can never reach a self-hosted instance, so
 * nothing arrives unless something here asks for it.
 *
 * Failures are swallowed on purpose. A drain that cannot reach the marketplace
 * is not something the user did, and a toast on every 60 s tick would be
 * unusable; the outcome surfaces as `last_sync_at` / `last_sync_error` on the
 * connection, which the marketplace pages render as a chip.
 */
export function useMarketplaceSync() {
  const queryClient = useQueryClient();
  const { data: connection } = useMarketplaceConnection();

  const enabled = connection ? SYNCABLE_STATUSES.includes(connection.status) : false;
  const inFlight = useRef(false);

  const sync = useCallback(() => {
    if (!enabled || inFlight.current) return;
    // Polling a hidden tab wastes a request on the marketplace's rate limit
    // (120 GET /events per hour) for a page nobody is looking at.
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;

    inFlight.current = true;
    runSync()
      .then(() => {
        void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
      })
      .catch(() => {
        // Refresh the connection anyway: last_sync_error is how the failure
        // reaches the UI.
        void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.connection() });
      })
      .finally(() => {
        inFlight.current = false;
      });
  }, [enabled, queryClient]);

  useEffect(() => {
    if (!enabled) return undefined;

    sync();

    const onFocus = () => sync();
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') sync();
    };

    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibilityChange);
    const intervalId = window.setInterval(sync, SYNC_INTERVAL_MS);

    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.clearInterval(intervalId);
    };
  }, [enabled, sync]);
}
