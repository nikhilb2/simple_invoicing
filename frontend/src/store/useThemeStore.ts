import { create } from 'zustand';

export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_KEY = 'theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';
const THEME_COLORS: Record<ResolvedTheme, string> = { dark: '#08111f', light: '#f4f7fb' };

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark';
}

/** Pure: an explicit choice wins, "system" follows the device. */
export function resolveTheme(preference: ThemePreference, prefersDark: boolean): ResolvedTheme {
  if (preference === 'system') return prefersDark ? 'dark' : 'light';
  return preference;
}

function mediaQuery(): MediaQueryList | null {
  try {
    return typeof matchMedia === 'function' ? matchMedia(DARK_QUERY) : null;
  } catch {
    return null;
  }
}

function systemPrefersDark(): boolean {
  // No matchMedia: stay on the app's original dark look.
  return mediaQuery()?.matches ?? true;
}

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return isThemePreference(stored) ? stored : 'system';
  } catch {
    return 'system';
  }
}

function currentRoot(): HTMLElement | undefined {
  return typeof document === 'undefined' ? undefined : document.documentElement;
}

/** Prefer what the inline script in index.html already applied, so nothing flips. */
function readInitialResolved(preference: ThemePreference): ResolvedTheme {
  const applied = currentRoot()?.dataset?.theme;
  if (applied === 'light' || applied === 'dark') return applied;
  return resolveTheme(preference, systemPrefersDark());
}

function applyTheme(resolved: ResolvedTheme) {
  const root = currentRoot();
  if (!root) return;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  document.querySelector?.('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[resolved]);
}

type ThemeState = {
  preference: ThemePreference;
  /** What is actually showing; never "system". */
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
};

const initialPreference = readPreference();

export const useThemeStore = create<ThemeState>((set) => ({
  preference: initialPreference,
  resolved: readInitialResolved(initialPreference),
  setPreference: (preference) => {
    if (!isThemePreference(preference)) return;
    try {
      localStorage.setItem(THEME_KEY, preference);
    } catch {
      // Private browsing / storage disabled — the choice still applies for this session.
    }
    const resolved = resolveTheme(preference, systemPrefersDark());
    applyTheme(resolved);
    set({ preference, resolved });
  },
}));

let listening = false;

/**
 * Call once at app start. Re-resolves live when the OS setting changes, but only
 * while the preference is "system".
 */
export function initThemeListener() {
  if (listening) return;
  const mql = mediaQuery();
  if (!mql) return;
  listening = true;
  const onChange = (event: { matches: boolean }) => {
    const { preference } = useThemeStore.getState();
    if (preference !== 'system') return;
    const resolved = resolveTheme(preference, event.matches);
    applyTheme(resolved);
    useThemeStore.setState({ resolved });
  };
  if (typeof mql.addEventListener === 'function') mql.addEventListener('change', onChange);
  else mql.addListener?.(onChange); // Safari < 14
}
