export const GITHUB_REPO_URL = 'https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software';
export const GITHUB_REPO_API_URL = 'https://api.github.com/repos/nikhilb2/simple-invoicing-free-gst-billing-software';

const STORAGE_KEY = 'github_stars';
const CACHE_TTL_MS = 60 * 60 * 1000;

type CachedStars = {
  /** Null until a fetch has succeeded at least once. */
  count: number | null;
  fetchedAt: number;
};

export function readCachedStars(): CachedStars | null {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed?.fetchedAt !== 'number') return null;
    return { count: parseStarCount(parsed), fetchedAt: parsed.fetchedAt };
  } catch {
    // Malformed JSON, or localStorage unavailable in a privacy mode.
    return null;
  }
}

export function writeCachedStars(count: number | null, fetchedAt: number): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify({ count, fetchedAt }));
  } catch {
    // Storage full or unavailable: the count is just fetched again next time.
  }
}

export function isStarCacheFresh(cached: CachedStars | null, now: number): boolean {
  return cached !== null && now - cached.fetchedAt < CACHE_TTL_MS;
}

/** Reads the count off either a cached entry or the GitHub repo payload. */
function parseStarCount(payload: { count?: unknown; stargazers_count?: unknown } | null): number | null {
  const value = payload?.stargazers_count ?? payload?.count;
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

export function parseRepoStars(payload: unknown): number | null {
  return parseStarCount(payload as { stargazers_count?: unknown } | null);
}

export function formatStarCount(count: number): string {
  return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(count);
}
