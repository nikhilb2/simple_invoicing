import { useEffect, useState } from 'react';

/**
 * Subscribes to a CSS media query from JS.
 *
 * For layout, prefer a media query in styles.css — this is for the cases CSS
 * can't reach, like the chart props Recharts only takes as numbers.
 */
export default function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const list = window.matchMedia(query);
    // Re-read on subscribe: the query may have changed since the last render.
    setMatches(list.matches);

    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

/** The width the app switches to its narrow layout at, per styles.css. */
export const NARROW_QUERY = '(max-width: 720px)';
