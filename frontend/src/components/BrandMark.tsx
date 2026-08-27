interface BrandMarkProps {
  /** Rendered edge length in px. Detail is chosen from this, not passed in. */
  size?: number;
  className?: string;
}

/**
 * The Simple Invoicing mark: an invoice sheet with a folded corner, ruled with
 * line items, the shortest rule accented as the total.
 *
 * The sheet inherits `currentColor` so it picks up whatever text colour its
 * container sets (sidebar text, a light print surface, the accent tile in a
 * knockout); only the total rule is pinned to the brand accent.
 *
 * Detail thins out as the mark shrinks — three rules, then two, then one — and
 * the stroke thickens to compensate. Drawn at 48px the full ruling reads; kept
 * at 48px detail down at favicon size it turns into a grey smudge.
 */
export default function BrandMark({ size = 28, className }: BrandMarkProps) {
  const rules = size >= 40 ? 3 : size >= 22 ? 2 : 1;
  const stroke = rules === 3 ? 3.4 : rules === 2 ? 4.2 : 6.5;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      className={className}
      aria-hidden="true"
      focusable="false"
      style={{ flexShrink: 0 }}
    >
      {rules === 1 ? (
        // The fold is the first thing to go: at 16px it closes up into a blob.
        // A slightly tighter sheet keeps the heavier stroke off the edges.
        <path
          d="M19 8 H37 L51 22 V52 A5 5 0 0 1 46 57 H19 A5 5 0 0 1 14 52 V13 A5 5 0 0 1 19 8 Z"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinejoin="round"
        />
      ) : (
        <>
          <path
            d="M19 7 H38 L52 21 V53 A5 5 0 0 1 47 58 H19 A5 5 0 0 1 14 53 V12 A5 5 0 0 1 19 7 Z"
            stroke="currentColor"
            strokeWidth={stroke}
            strokeLinejoin="round"
          />
          <path
            d="M38 8 V18 A3 3 0 0 0 41 21 H51"
            stroke="currentColor"
            strokeWidth={stroke}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </>
      )}

      {rules === 3 && (
        <>
          <path d="M23 33 H43" stroke="var(--muted)" strokeWidth={stroke} strokeLinecap="round" />
          <path d="M23 41 H43" stroke="var(--muted)" strokeWidth={stroke} strokeLinecap="round" />
          <path d="M23 49 H35" stroke="var(--accent)" strokeWidth={stroke} strokeLinecap="round" />
        </>
      )}
      {rules === 2 && (
        <>
          <path d="M23 34 H43" stroke="var(--muted)" strokeWidth={stroke} strokeLinecap="round" />
          <path d="M23 47 H35" stroke="var(--accent)" strokeWidth={stroke} strokeLinecap="round" />
        </>
      )}
      {rules === 1 && (
        <path d="M24 43 H36" stroke="var(--accent)" strokeWidth={stroke} strokeLinecap="round" />
      )}
    </svg>
  );
}
