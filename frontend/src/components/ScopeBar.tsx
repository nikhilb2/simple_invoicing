import { useEffect, useRef } from 'react';

type ScopeBarProps = {
  /** A full-width line above the fields — range presets, mode chips. */
  presets?: React.ReactNode;
  /** The filter controls themselves. Reflow on their own via auto-fit. */
  children: React.ReactNode;
  /** Totals for the current scope, read rather than acted on. */
  metrics?: React.ReactNode;
  /** Exports and other actions carrying this scope. */
  actions?: React.ReactNode;
  className?: string;
};

/**
 * The filter row that sits above a report's result, full width, and sticks
 * under the app header while the result scrolls.
 *
 * It also measures itself and publishes the height as `--scope-bar-h` on the
 * enclosing page, which is what lets a table header below it stick *directly*
 * underneath rather than at a hard-coded offset that goes wrong the moment the
 * bar wraps to a second line.
 */
export default function ScopeBar({ presets, children, metrics, actions, className }: ScopeBarProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // The page, not :root — the variable only means anything to the result
    // rendered beneath this bar, and a second page must not inherit a stale one.
    const host = (el.closest('.page-grid') ?? el.parentElement) as HTMLElement | null;
    if (!host) return;

    const publish = () => host.style.setProperty('--scope-bar-h', `${Math.round(el.offsetHeight)}px`);
    publish();

    const observer = new ResizeObserver(publish);
    observer.observe(el);
    return () => {
      observer.disconnect();
      host.style.removeProperty('--scope-bar-h');
    };
  }, []);

  return (
    <section ref={ref} className={`scope-bar${className ? ` ${className}` : ''}`}>
      {presets ? <div className="scope-bar__row">{presets}</div> : null}
      <div className="scope-bar__fields">{children}</div>
      {metrics || actions ? (
        <div className="scope-bar__trailing">
          {metrics ? <div className="metric-strip">{metrics}</div> : null}
          {actions ? <div className="scope-bar__actions">{actions}</div> : null}
        </div>
      ) : null}
    </section>
  );
}

/** A label-over-figure total, the inline form of `.summary-box`. */
export function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  tone?: 'accent' | 'danger';
}) {
  return (
    <div className={`metric${tone ? ` metric--${tone}` : ''}`}>
      <span className="metric__label">{label}</span>
      <span className="metric__value">{value}</span>
    </div>
  );
}
