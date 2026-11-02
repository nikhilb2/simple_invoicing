import { Link } from 'react-router-dom';
import { Store } from 'lucide-react';
import EmptyState from '../../../components/EmptyState';
import type { MarketplaceConnection } from '../../../features/marketplace/types';

type MarketplaceGateProps = {
  connection: MarketplaceConnection | undefined;
  isLoading: boolean;
  /** True when the connection request itself failed. */
  failed: boolean;
  children: React.ReactNode;
};

/** Statuses that mean a connection row exists. Whether it can currently *trade*
 *  is a separate question each page answers for itself. */
const HAS_CONNECTION = ['connected', 'pending_approval', 'suspended', 'unauthorized'];

/**
 * Renders the "connect first" state instead of the page when this company has
 * no marketplace connection.
 *
 * The nav group is deliberately always visible — `visiblePrimaryNav(isAdmin)`
 * knows nothing about connection state — so every marketplace page has to be
 * able to explain itself to someone who has never connected.
 */
export default function MarketplaceGate({ connection, isLoading, failed, children }: MarketplaceGateProps) {
  if (isLoading) {
    return <EmptyState message="Checking marketplace connection…" />;
  }

  // A failed probe is treated as "not connected" rather than as an error: the
  // most common cause is a backend that has no connection row for this company.
  const status = failed ? 'unregistered' : connection?.status;

  if (!status || !HAS_CONNECTION.includes(status)) {
    return (
      <div className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Marketplace</p>
            <h2 className="nav-panel__title">Not connected</h2>
          </div>
        </div>
        <EmptyState
          message="This company is not connected to a marketplace. Connect one to browse listings from other businesses, publish your own surplus stock, and trade."
          action={
            <Link to="/settings/marketplace" className="button button--primary">
              <Store size={16} />
              Connect to a marketplace
            </Link>
          }
        />
      </div>
    );
  }

  return <>{children}</>;
}
