import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resolveTheme } from './useThemeStore';

type Listener = (event: { matches: boolean }) => void;

let data: Record<string, string>;
let storageThrows: boolean;
let prefersDark: boolean;
let listeners: Listener[];
let root: { dataset: Record<string, string>; style: Record<string, string> };
let meta: { content: string; setAttribute: (k: string, v: string) => void };

function stubEnvironment() {
  data = {};
  storageThrows = false;
  listeners = [];
  root = { dataset: {}, style: {} };
  meta = {
    content: '',
    setAttribute(_k, v) {
      this.content = v;
    },
  };
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => {
      if (storageThrows) throw new Error('denied');
      return k in data ? data[k] : null;
    },
    setItem: (k: string, v: string) => {
      if (storageThrows) throw new Error('denied');
      data[k] = String(v);
    },
  });
  vi.stubGlobal('matchMedia', () => ({
    get matches() {
      return prefersDark;
    },
    addEventListener: (_t: string, fn: Listener) => listeners.push(fn),
  }));
  vi.stubGlobal('document', {
    documentElement: root,
    querySelector: () => meta,
  });
}

/** The store reads its environment when the module loads, so re-import per test. */
async function loadStore() {
  vi.resetModules();
  return import('./useThemeStore');
}

function fireMediaChange(matches: boolean) {
  prefersDark = matches;
  listeners.forEach((fn) => fn({ matches }));
}

beforeEach(() => {
  prefersDark = true;
  stubEnvironment();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('resolveTheme', () => {
  it.each([
    ['system', true, 'dark'],
    ['system', false, 'light'],
    ['light', true, 'light'],
    ['light', false, 'light'],
    ['dark', true, 'dark'],
    ['dark', false, 'dark'],
  ] as const)('%s with prefersDark=%s -> %s', (pref, dark, expected) => {
    expect(resolveTheme(pref, dark)).toBe(expected);
  });
});

describe('useThemeStore', () => {
  it('defaults to system and resolves from the OS', async () => {
    prefersDark = false;
    const { useThemeStore } = await loadStore();
    expect(useThemeStore.getState().preference).toBe('system');
    expect(useThemeStore.getState().resolved).toBe('light');
  });

  it('reads a stored preference', async () => {
    data.theme = 'dark';
    prefersDark = false;
    const { useThemeStore } = await loadStore();
    expect(useThemeStore.getState().preference).toBe('dark');
    expect(useThemeStore.getState().resolved).toBe('dark');
  });

  it('trusts the theme the inline script already applied', async () => {
    root.dataset.theme = 'light';
    prefersDark = true;
    const { useThemeStore } = await loadStore();
    expect(useThemeStore.getState().resolved).toBe('light');
  });

  it.each(['', 'sepia', 'DARK', 'null'])('falls back to system for stored %j', async (bad) => {
    data.theme = bad;
    const { useThemeStore } = await loadStore();
    expect(useThemeStore.getState().preference).toBe('system');
  });

  it('persists and applies a choice', async () => {
    const { useThemeStore } = await loadStore();
    useThemeStore.getState().setPreference('light');
    expect(data.theme).toBe('light');
    expect(root.dataset.theme).toBe('light');
    expect(root.style.colorScheme).toBe('light');
    expect(meta.content).toBe('#f4f7fb');
    useThemeStore.getState().setPreference('dark');
    expect(data.theme).toBe('dark');
    expect(root.dataset.theme).toBe('dark');
    expect(meta.content).toBe('#08111f');
  });

  it('never writes "system" to data-theme', async () => {
    prefersDark = false;
    const { useThemeStore } = await loadStore();
    useThemeStore.getState().setPreference('system');
    expect(data.theme).toBe('system');
    expect(root.dataset.theme).toBe('light');
  });

  it('does not crash when storage throws', async () => {
    storageThrows = true;
    const { useThemeStore } = await loadStore();
    expect(useThemeStore.getState().preference).toBe('system');
    expect(() => useThemeStore.getState().setPreference('light')).not.toThrow();
    expect(useThemeStore.getState().preference).toBe('light');
    expect(root.dataset.theme).toBe('light');
  });

  it('re-resolves on a media change while preference is system', async () => {
    prefersDark = true;
    const { useThemeStore, initThemeListener } = await loadStore();
    initThemeListener();
    initThemeListener(); // idempotent
    expect(listeners).toHaveLength(1);

    fireMediaChange(false);
    expect(useThemeStore.getState().resolved).toBe('light');
    expect(root.dataset.theme).toBe('light');
    fireMediaChange(true);
    expect(root.dataset.theme).toBe('dark');
  });

  it('ignores media changes once an explicit choice is made', async () => {
    const { useThemeStore, initThemeListener } = await loadStore();
    initThemeListener();
    useThemeStore.getState().setPreference('dark');
    fireMediaChange(false);
    expect(useThemeStore.getState().resolved).toBe('dark');
    expect(root.dataset.theme).toBe('dark');
  });
});
