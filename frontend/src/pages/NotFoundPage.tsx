/**
 * NotFoundPage.tsx
 *
 * Shown for unknown URLs (the `*` catch-all route in App.tsx) instead of
 * silently redirecting to the dashboard. It shows the attempted path and a
 * button back to the dashboard, reusing the shared EmptyState component.
 */
import { useLocation, useNavigate } from 'react-router-dom';
import EmptyState from '../components/EmptyState';

export default function NotFoundPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  return (
    <EmptyState
      message={`Page not found: ${pathname}`}
      action={{ label: 'Back to dashboard', onClick: () => navigate('/') }}
    />
  );
}
