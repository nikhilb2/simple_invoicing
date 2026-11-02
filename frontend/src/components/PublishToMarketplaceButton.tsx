import { useCallback, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Store } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from './StatusToasts';
import { useEscapeClose } from '../hooks/useEscapeClose';
import ListingFormModal, {
  type ListingFormValues,
} from '../pages/marketplace/components/ListingFormModal';
import { createListing, fetchMyListings } from '../features/marketplace/api';
import { marketplaceQueryKeys } from '../features/marketplace/queryKeys';
import { useMarketplaceConnection } from '../features/marketplace/useMarketplaceSync';
import type { PaginatedProducts, Product } from '../types/api';

/**
 * Resolves one product for a page that holds only its id.
 *
 * It searches by name rather than reading the shared products list, which the
 * backend caps at 500 rows — for a catalogue larger than that the list simply
 * would not contain product #501 and the form would wait forever on a query
 * that had already succeeded. `search` matches name or SKU, so this narrows to
 * a handful and the id picks the right one even when names collide.
 */
async function fetchProductById(productId: number, productName: string): Promise<Product> {
  const res = await api.get<PaginatedProducts>('/products/', {
    params: { search: productName, page_size: 100 },
  });
  const match = res.data.items.find((candidate) => candidate.id === productId);
  if (!match) throw new Error('Product not found');
  return match;
}

type PublishToMarketplaceButtonProps = {
  productId: number;
  productName: string;
  /**
   * The full product, when the host page already holds one. Inventory rows do
   * not — they carry no GST rate or HSN/SAC — so those pages pass only the id
   * and the product master is looked up when the form opens.
   */
  product?: Product;
  /** Stock on hand, to seed the advertised quantity. Advisory, as ever. */
  quantity?: number | string | null;
  /** `icon` matches the Products row actions, `small` the Inventory ones. */
  variant?: 'icon' | 'small';
};

/**
 * Publishes one product to the marketplace without leaving Products or
 * Inventory.
 *
 * It renders nothing at all unless this company has a *connected* marketplace.
 * That is a deliberate departure from the marketplace pages, which always
 * render and explain themselves: a row action is not a destination, and a
 * button that only ever opens a "you are not connected" message is noise on
 * every row of a page most users reach for other reasons. The nav group and
 * the dashboard card are where an unconnected company is told the feature
 * exists.
 */
export default function PublishToMarketplaceButton({
  productId,
  productName,
  product,
  quantity,
  variant = 'icon',
}: PublishToMarketplaceButtonProps) {
  const queryClient = useQueryClient();
  const connectionQuery = useMarketplaceConnection();
  const connected = connectionQuery.data?.status === 'connected';

  const [open, setOpen] = useState(false);
  const [formError, setFormError] = useState('');

  useEscapeClose(useCallback(() => { setOpen(false); setFormError(''); }, []));
  const [success, setSuccess] = useState('');

  // Shares MyListingsPage's cache entry, so this costs one request per page
  // however many rows render the button.
  const listingsQuery = useQuery({
    queryKey: marketplaceQueryKeys.listings(),
    queryFn: fetchMyListings,
    enabled: connected,
  });

  // Only fetched when the caller could not supply the product itself, and only
  // once the form is actually opened.
  const productQuery = useQuery({
    queryKey: ['products', 'byId', productId],
    queryFn: () => fetchProductById(productId, productName),
    enabled: connected && open && !product,
    retry: false,
  });

  const publishMutation = useMutation({
    mutationFn: (values: ListingFormValues) =>
      createListing({
        product_id: productId,
        asking_price: values.askingPrice.trim(),
        available_quantity: values.availableQuantity.trim(),
        title: values.title.trim(),
        description: values.description.trim(),
        min_order_quantity: values.minOrderQuantity.trim() || null,
        max_order_quantity: values.maxOrderQuantity.trim() || null,
      }),
    onSuccess: () => {
      setSuccess(`${productName} is published to the marketplace.`);
      setOpen(false);
      setFormError('');
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => setFormError(getApiErrorMessage(err, 'Unable to publish this product')),
  });

  if (!connected) return null;

  /**
   * Any listing at all blocks re-publishing, withdrawn ones included. The route
   * excludes withdrawn from its 409 check, but
   * `ux_marketplace_listings_company_product` is unconditional — so a second
   * publish gets past the check and dies on the constraint. Offering the button
   * would hand the user a 500, not a listing.
   */
  const existingListing = listingsQuery.data?.find((listing) => listing.product_id === productId);
  const blockedLabel = existingListing
    ? existingListing.status === 'withdrawn'
      ? `${productName} was listed and withdrawn — it cannot be re-published`
      : `${productName} is already listed on the marketplace`
    : `Publish ${productName} to the marketplace`;

  const resolvedProduct = product ?? productQuery.data;

  const className =
    variant === 'small' ? 'button button--ghost button--small' : 'button button--ghost button--icon';
  const style = variant === 'small' ? { padding: '4px 8px' } : undefined;
  const iconSize = variant === 'small' ? 15 : 16;

  return (
    <>
      <button
        type="button"
        className={className}
        style={style}
        onClick={() => { setFormError(''); setOpen(true); }}
        disabled={Boolean(existingListing) || listingsQuery.isLoading}
        title={blockedLabel}
        aria-label={blockedLabel}
      >
        <Store size={iconSize} />
      </button>

      {open && (
        resolvedProduct ? (
          <ListingFormModal
            products={[]}
            lockedProduct={resolvedProduct}
            initialQuantity={
              quantity === null || quantity === undefined ? undefined : String(quantity)
            }
            submitting={publishMutation.isPending}
            error={formError}
            onClose={() => { setOpen(false); setFormError(''); }}
            onSubmit={(values) => publishMutation.mutate(values)}
          />
        ) : (
          <div
            className="modal-overlay"
            role="dialog"
            aria-modal="true"
            aria-label={`Publish ${productName}`}
            onClick={() => setOpen(false)}
          >
            <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
              <p className="empty-state">
                {productQuery.isError
                  ? `Could not load ${productName}. Publish it from My listings instead.`
                  : 'Loading product…'}
              </p>
              <div className="button-row" style={{ justifyContent: 'flex-end' }}>
                <button type="button" className="button button--ghost" onClick={() => setOpen(false)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        )
      )}

      <StatusToasts
        error=""
        success={success}
        onClearError={() => {}}
        onClearSuccess={() => setSuccess('')}
      />
    </>
  );
}
