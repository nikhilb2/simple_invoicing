import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResolvedTheme, ThemePreference } from '../store/useThemeStore';
import ThemeToggle from './ThemeToggle';

const store = vi.hoisted(() => ({
  state: {
    preference: 'system' as ThemePreference,
    resolved: 'light' as ResolvedTheme,
    setPreference: vi.fn(),
  },
}));

// renderToString reads a zustand store's initial state and ignores setState, so
// the hook is replaced and the component is called directly for its element.
vi.mock('../store/useThemeStore', () => ({
  useThemeStore: (selector: (state: typeof store.state) => unknown) => selector(store.state),
}));

describe('ThemeToggle', () => {
  beforeEach(() => {
    store.state.setPreference.mockClear();
  });

  it.each([
    { resolved: 'light', next: 'dark' },
    { resolved: 'dark', next: 'light' },
  ] as const)('offers and applies $next while $resolved is showing', ({ resolved, next }) => {
    store.state.resolved = resolved;

    const button = ThemeToggle();
    expect(button.props['aria-label']).toBe(`Switch to ${next} theme`);

    button.props.onClick();
    expect(store.state.setPreference).toHaveBeenCalledWith(next);
  });

  it('flips what is showing when the preference is system', () => {
    store.state.preference = 'system';
    store.state.resolved = 'dark';

    ThemeToggle().props.onClick();
    expect(store.state.setPreference).toHaveBeenCalledWith('light');
  });
});
