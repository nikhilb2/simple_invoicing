import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  formatStarCount,
  isStarCacheFresh,
  parseRepoStars,
  readCachedStars,
  writeCachedStars,
} from './githubStars';

function stubStorage(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial));
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => store.set(key, value),
  });
}

afterEach(() => vi.unstubAllGlobals());

describe('formatStarCount', () => {
  it('shows small counts as they are', () => {
    expect(formatStarCount(0)).toBe('0');
    expect(formatStarCount(11)).toBe('11');
    expect(formatStarCount(999)).toBe('999');
  });

  it('abbreviates large counts so the button keeps its width', () => {
    expect(formatStarCount(1250)).toBe('1.3K');
    expect(formatStarCount(12000)).toBe('12K');
  });
});

describe('parseRepoStars', () => {
  it('reads the count from the GitHub payload', () => {
    expect(parseRepoStars({ stargazers_count: 11 })).toBe(11);
    expect(parseRepoStars({ stargazers_count: 0 })).toBe(0);
  });

  it('rejects anything else', () => {
    expect(parseRepoStars(null)).toBeNull();
    expect(parseRepoStars({ message: 'API rate limit exceeded' })).toBeNull();
    expect(parseRepoStars({ stargazers_count: '11' })).toBeNull();
  });
});

describe('star cache', () => {
  it('round-trips a count', () => {
    stubStorage();
    writeCachedStars(11, 1000);
    expect(readCachedStars()).toEqual({ count: 11, fetchedAt: 1000 });
  });

  it('remembers a failed fetch, so a rate limit is not retried on every page', () => {
    stubStorage();
    writeCachedStars(null, 1000);
    expect(readCachedStars()).toEqual({ count: null, fetchedAt: 1000 });
    expect(isStarCacheFresh(readCachedStars(), 1000 + 60_000)).toBe(true);
  });

  it('ignores a malformed entry', () => {
    stubStorage({ github_stars: 'not json' });
    expect(readCachedStars()).toBeNull();
  });

  it('treats nothing cached as stale', () => {
    expect(isStarCacheFresh(null, 1000)).toBe(false);
  });

  it('expires after an hour', () => {
    const cached = { count: 11, fetchedAt: 0 };
    expect(isStarCacheFresh(cached, 59 * 60 * 1000)).toBe(true);
    expect(isStarCacheFresh(cached, 60 * 60 * 1000)).toBe(false);
  });
});
