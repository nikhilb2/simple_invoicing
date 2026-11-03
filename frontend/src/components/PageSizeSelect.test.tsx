import { describe, expect, it, vi } from 'vitest';
import { renderToString } from 'react-dom/server';
import PageSizeSelect, {
  DEFAULT_PAGE_SIZE,
  PAGE_SIZE_OPTIONS,
  readStoredPageSize,
  storePageSize,
} from './PageSizeSelect';

function fakeStorage(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
  };
}

describe('PageSizeSelect', () => {
  it('offers 20, 50 and 100 with the current value selected', () => {
    const html = renderToString(<PageSizeSelect id="rows-per-page" value={50} onChange={() => {}} />);

    expect(html).toContain('Rows per page');
    expect(html).toContain('id="rows-per-page"');
    for (const option of PAGE_SIZE_OPTIONS) {
      expect(html).toContain(`value="${option}"`);
    }
    expect(html).toContain('selected=""');
  });

  it('reads a stored choice and falls back for anything else', () => {
    vi.stubGlobal('localStorage', fakeStorage({ 'ledgers-page-size': '100' }));
    expect(readStoredPageSize('ledgers-page-size')).toBe(100);

    vi.stubGlobal('localStorage', fakeStorage({ 'ledgers-page-size': '7' }));
    expect(readStoredPageSize('ledgers-page-size')).toBe(DEFAULT_PAGE_SIZE);

    vi.stubGlobal('localStorage', fakeStorage({}));
    expect(readStoredPageSize('ledgers-page-size')).toBe(DEFAULT_PAGE_SIZE);
    vi.unstubAllGlobals();
  });

  it('stores a choice and survives storage throwing', () => {
    const storage = fakeStorage({});
    vi.stubGlobal('localStorage', storage);
    storePageSize('ledgers-page-size', 50);
    expect(storage.getItem('ledgers-page-size')).toBe('50');
    vi.unstubAllGlobals();

    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('storage unavailable');
      },
      setItem: () => {
        throw new Error('storage unavailable');
      },
    });
    expect(readStoredPageSize('ledgers-page-size')).toBe(DEFAULT_PAGE_SIZE);
    expect(() => storePageSize('ledgers-page-size', 50)).not.toThrow();
    vi.unstubAllGlobals();
  });
});
