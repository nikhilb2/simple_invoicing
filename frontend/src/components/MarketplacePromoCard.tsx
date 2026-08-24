import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Store, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useMarketplaceConnection } from '../features/marketplace/useMarketplaceSync';

/**
 * The two variants pitch different things, so they are dismissed separately:
 * someone who waved away "sell your surplus stock" before connecting has still
 * never been told that publishing now lives on their product rows.
 */
const DISMISS_KEYS = {
  connect: 'dashboard_marketplace_connect_promo_dismissed',
  publish: 'dashboard_marketplace_publish_promo_dismissed',
} as const;

/** localStorage is unavailable in some privacy modes; a promo card is not worth
 *  taking the dashboard down for. */
function readDismissed(key: string): boolean {
  try {
    return localStorage.getItem(key) === 'true';
  } catch {
    return false;
  }
}

function writeDismissed(key: string) {
  try {
    localStorage.setItem(key, 'true');
  } catch {
    /* ignore */
  }
}

/**
 * Tells the dashboard that surplus stock can go straight to the marketplace
 * from a Products or Inventory row.
 *
 * It says something different depending on what the company can act on: an
 * unconnected company is pointed at settings, a connected one at the rows that
 * now carry the button. Statuses in between — awaiting approval, suspended,
 * unauthorized — get nothing: those companies have a real problem the
 * marketplace settings page already nags about, and an advertisement on top of
 * it would be noise.
 *
 * The dismissal is per browser, following useSidebarStore's precedent of
 * reading localStorage in the state initializer rather than an effect, so the
 * card never flashes in before being hidden.
 */
export default function MarketplacePromoCard() {
  const [dismissed, setDismissed] = useState(() => ({
    connect: readDismissed(DISMISS_KEYS.connect),
    publish: readDismissed(DISMISS_KEYS.publish),
  }));
  const { isAdmin } = useAuth();
  const connectionQuery = useMarketplaceConnection();

  if (connectionQuery.isLoading) return null;

  // A failed probe means no connection row for this company, which is the same
  // thing as never having connected as far as this card is concerned.
  const status = connectionQuery.error ? 'unregistered' : connectionQuery.data?.status ?? 'unregistered';
  const connected = status === 'connected';
  if (!connected && status !== 'unregistered' && status !== 'disconnected') return null;

  const variant = connected ? 'publish' : 'connect';
  if (dismissed[variant]) return null;

  const dismiss = () => {
    writeDismissed(DISMISS_KEYS[variant]);
    setDismissed((prev) => ({ ...prev, [variant]: true }));
  };

  return (
    <section className="panel stack promo-card">
      <div className="panel__header">
        <div>
          <p className="eyebrow">New</p>
          <h2 className="nav-panel__title">
            {connected ? 'Publish stock without leaving your catalogue' : 'Sell your surplus stock'}
          </h2>
        </div>
        <div className="promo-card__header-actions">
          <div className="status-chip">
            <Store size={15} />
            Marketplace
          </div>
          <button
            type="button"
            className="button button--ghost button--icon"
            onClick={dismiss}
            title="Dismiss this announcement"
            aria-label="Dismiss this announcement"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      <p className="section-copy">
        {connected ? (
          <>
            Every row in <strong>Products</strong> and <strong>Inventory</strong> now has a publish
            button — one click puts that item in front of every other business on your marketplace,
            no re-typing its GST rate, HSN/SAC or unit. You can enter the asking price either{' '}
            <strong>excluding or including GST</strong>, and the form shows what a buyer will
            actually pay per unit before you publish.
          </>
        ) : (
          <>
            Connect a marketplace and you can publish surplus stock straight from a{' '}
            <strong>Products</strong> or <strong>Inventory</strong> row, browse what every other
            business is selling, and have accepted orders post into your books as invoices. Prices
            can be entered excluding or including GST — no money moves through the marketplace, you
            settle with the other business directly.
            {!isAdmin && ' Connecting one is an admin job — ask yours to set it up.'}
          </>
        )}
      </p>

      <div className="button-row">
        {connected ? (
          <>
            <Link to="/products" className="button button--primary button--small">
              <Store size={15} />
              Publish from Products
            </Link>
            <Link to="/marketplace/listings" className="button button--secondary button--small">
              View my listings
            </Link>
          </>
        ) : (
          <>
            {isAdmin && (
              <Link to="/marketplace/settings" className="button button--primary button--small">
                <Store size={15} />
                Connect to a marketplace
              </Link>
            )}
            <Link
              to="/marketplace"
              className={`button button--small ${isAdmin ? 'button--secondary' : 'button--primary'}`}
            >
              Browse listings
            </Link>
          </>
        )}
      </div>
    </section>
  );
}
