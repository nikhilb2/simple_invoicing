/**
 * The version this bundle was built as, injected by the `build-version` plugin
 * in vite.config.ts. The same value is written to `/version.json` next to the
 * bundle, so a tab can tell whether the server has moved on without it.
 */
export const BUILD_VERSION: string = __BUILD_VERSION__;

/** Where the build stamp is served from, on the app's own origin. */
export const VERSION_URL = '/version.json';

/**
 * Read a version out of a `/version.json` response body.
 *
 * Returns null for anything that is not a `{ version: <non-empty string> }`
 * object. That covers the two failure modes worth defending against: an SPA
 * fallback handing back index.html, and a file caught mid-write. A null means
 * "no information" and is never treated as a version change.
 */
export function parseVersionPayload(text: string): string | null {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return null;
  }

  if (typeof payload !== 'object' || payload === null) return null;

  const { version } = payload as { version?: unknown };
  if (typeof version !== 'string' || version.trim() === '') return null;

  return version;
}

/**
 * Whether the running tab should be told to reload.
 *
 * Compares by plain inequality rather than "is newer" on purpose: a rollback
 * puts a different build on the server and the tab should pick that up too.
 * `dismissed` is the version the user has already waved away, so a single
 * dismissal stays dismissed while a *later* deploy prompts again.
 */
export function shouldPromptReload(
  current: string,
  fetched: string | null,
  dismissed: string | null,
): boolean {
  if (fetched === null) return false;
  if (fetched === current) return false;
  return fetched !== dismissed;
}
