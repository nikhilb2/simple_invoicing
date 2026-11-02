import { AlertTriangle, RefreshCw } from 'lucide-react';
import type { MarketplaceConnection } from '../../../features/marketplace/types';
import { formatRelativeTime } from './format';

/**
 * The only place a sync failure surfaces. The poll runs every 60 s in the
 * background and must never raise a toast, so this chip carries the whole
 * story: when the feed was last drained, and why it last failed.
 */
export default function SyncStatusChip({ connection }: { connection: MarketplaceConnection }) {
  if (connection.last_sync_error) {
    return (
      <span
        className="status-chip status-chip--warning"
        title={connection.last_sync_error}
      >
        <AlertTriangle size={13} />
        Sync failing · last synced {formatRelativeTime(connection.last_sync_at)}
      </span>
    );
  }

  return (
    <span className="status-chip">
      <RefreshCw size={13} />
      Synced {formatRelativeTime(connection.last_sync_at)}
    </span>
  );
}
