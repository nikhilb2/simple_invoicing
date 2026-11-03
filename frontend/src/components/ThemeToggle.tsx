import { Moon, Sun } from 'lucide-react';
import { useThemeStore } from '../store/useThemeStore';

/** Flips what is showing. "System" stays available under Settings → Appearance. */
export default function ThemeToggle() {
  const resolved = useThemeStore((state) => state.resolved);
  const setPreference = useThemeStore((state) => state.setPreference);
  const next = resolved === 'dark' ? 'light' : 'dark';
  const label = `Switch to ${next} theme`;
  const Icon = next === 'dark' ? Moon : Sun;

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setPreference(next)}
      aria-label={label}
      title={label}
    >
      <Icon size={18} aria-hidden="true" />
    </button>
  );
}
