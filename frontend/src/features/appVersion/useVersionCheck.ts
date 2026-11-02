import { useCallback, useEffect, useRef, useState } from 'react';
import { BUILD_VERSION, VERSION_URL, parseVersionPayload, shouldPromptReload } from './version';

const CHECK_INTERVAL_MS = 60_000;

type VersionCheck = {
  /** The newer version on the server, or null when the tab is up to date. */
  updateVersion: string | null;
  /** Suppress the prompt for the current version until a later deploy. */
  dismiss: () => void;
};

/**
 * Polls the build stamp so a long-lived tab finds out that a new image has been
 * rolled out. Nothing else tells it: the assets it is running are cached
 * `immutable` for a year, and the API cannot push.
 *
 * Follows the same shape as useMarketplaceSync — 60 s interval, no overlapping
 * requests, idle while the tab is hidden, re-checked the moment it comes back —
 * and swallows failures for the same reason: a stamp that cannot be fetched is
 * not something the user did anything about.
 */
export function useVersionCheck(): VersionCheck {
  const [updateVersion, setUpdateVersion] = useState<string | null>(null);
  const inFlight = useRef(false);
  const dismissed = useRef<string | null>(null);

  const check = useCallback(() => {
    if (inFlight.current) return;
    // Nobody is looking at a hidden tab, and it gets a check on the way back in.
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;

    inFlight.current = true;
    // Plain fetch, not the axios client: that instance prefixes the API base
    // URL and attaches auth headers, none of which belong on a static file
    // served from the app's own origin.
    fetch(VERSION_URL, { cache: 'no-store' })
      .then(response => (response.ok ? response.text() : null))
      .then(text => {
        const fetched = text === null ? null : parseVersionPayload(text);
        if (shouldPromptReload(BUILD_VERSION, fetched, dismissed.current)) {
          setUpdateVersion(fetched);
        }
      })
      .catch(() => {
        // Offline, or mid-rollout with no pod answering. The next tick retries.
      })
      .finally(() => {
        inFlight.current = false;
      });
  }, []);

  useEffect(() => {
    check();

    const onFocus = () => check();
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') check();
    };

    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibilityChange);
    const intervalId = window.setInterval(check, CHECK_INTERVAL_MS);

    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.clearInterval(intervalId);
    };
  }, [check]);

  const dismiss = useCallback(() => {
    setUpdateVersion(current => {
      dismissed.current = current;
      return null;
    });
  }, []);

  return { updateVersion, dismiss };
}
