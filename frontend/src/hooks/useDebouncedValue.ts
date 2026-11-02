import { useEffect, useState } from 'react';

/**
 * Trails `value` by `delay`, so a value that changes on every keystroke can
 * drive a request without firing one per character.
 *
 * The list pages type straight into a `useEffect` dependency, which meant a
 * six-letter search sent six requests and let an early one land last. Debounce
 * removes the volume; the caller still needs a race guard if responses can
 * overtake each other.
 */
export default function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
