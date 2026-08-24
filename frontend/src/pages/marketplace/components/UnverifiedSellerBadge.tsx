import { ShieldAlert } from 'lucide-react';

export const UNVERIFIED_SELLER_COPY =
  'Sellers are self-declared. The marketplace does not verify GSTIN ownership — verify the counterparty independently before shipping or paying.';

/**
 * Required on every counterparty the marketplace shows. GSTIN ownership is not
 * verified in v1 (MARKETPLACE.md §8), and an unbadged seller name reads as a
 * vouched-for identity, which it is not.
 */
export default function UnverifiedSellerBadge() {
  return (
    <span className="marketplace-unverified" title={UNVERIFIED_SELLER_COPY}>
      <ShieldAlert size={12} />
      Unverified
    </span>
  );
}
