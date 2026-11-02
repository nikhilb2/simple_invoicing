/**
 * LoadingState.tsx
 *
 * A shared component used to display a consistent loading message while a
 * list or panel is fetching data.
 *
 * Use this instead of EmptyState (which is meant for empty/no-results) or
 * ad-hoc inline text whenever a list page is loading, so loading states
 * look and announce the same way across the application.
 */

interface LoadingStateProps {
  /** The loading message to show the user */
  message: string;
}

/**
 * Renders a loading placeholder.
 * It uses the existing `.empty-state` CSS class defined in styles.css
 * to maintain visual consistency with the rest of the application.
 * role="status" with aria-live="polite" lets screen readers announce it.
 */
export default function LoadingState({ message }: LoadingStateProps) {
  return (
    <div className="empty-state" role="status" aria-live="polite">
      <p>{message}</p>
    </div>
  );
}
