/**
 * EmptyState.tsx
 * 
 * A shared component used to display a consistent message and optional 
 * Call-to-Action (CTA) when a list or panel has no content to display.
 * 
 * This helps standardize "empty" and "no-results" states across the application,
 * making the UI more predictable and action-oriented for open-source contributors
 * and end-users alike.
 */
import { ReactNode, isValidElement } from 'react';

interface EmptyStateProps {
  /** The descriptive message to show the user */
  message: string;
  /** Optional button config or custom React node to encourage user action */
  action?: {
    label: string;
    onClick: () => void;
  } | ReactNode;
}

/**
 * Renders an empty state placeholder.
 * It uses the existing `.empty-state` CSS class defined in styles.css
 * to maintain visual consistency with the rest of the application.
 */
export default function EmptyState({ message, action }: EmptyStateProps) {
  const renderAction = () => {
    if (!action) return null;

    // If it's already a React element, just render it
    if (isValidElement(action)) return action;

    // If it's the config object, render a button
    const config = action as { label: string; onClick: () => void };
    if (config.label && config.onClick) {
      return (
        <button className="button" onClick={config.onClick}>
          {config.label}
        </button>
      );
    }

    return null;
  };

  return (
    <div className="empty-state">
      <p>{message}</p>
      {/* If an action is provided, we display it centered below the text */}
      {action && (
        <div className="button-row" style={{ justifyContent: 'center', marginTop: '16px' }}>
          {renderAction()}
        </div>
      )}
    </div>
  );
}
