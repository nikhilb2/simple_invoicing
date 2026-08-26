import { useEffect } from 'react';
import { create } from 'zustand';
import { useShallow } from 'zustand/shallow';
import api from '../api/client';
import { useAuth } from './AuthContext';
import { ACTION_KEYS, DEFAULT_SHORTCUTS, type ActionKey } from '../utils/shortcutDefaults';

type ShortcutEntry = {
  action_key: string;
  shortcut_key: string;
};

type ShortcutsListResponse = {
  shortcuts: ShortcutEntry[];
};

type ShortcutsStore = {
  shortcutsMap: Record<ActionKey, string>;
  handlers: Map<ActionKey, () => void>;
  shortcutFor: (key: ActionKey) => string;
  registerAction: (key: ActionKey, handler: () => void) => () => void;
  refetchShortcuts: () => Promise<void>;
};

const useShortcutsStore = create<ShortcutsStore>((set, get) => ({
  shortcutsMap: { ...DEFAULT_SHORTCUTS },
  handlers: new Map(),

  shortcutFor: (key) => get().shortcutsMap[key] ?? DEFAULT_SHORTCUTS[key],

  registerAction: (key, handler) => {
    get().handlers.set(key, handler);
    return () => {
      get().handlers.delete(key);
    };
  },

  refetchShortcuts: async () => {
    try {
      const res = await api.get<ShortcutsListResponse>('/shortcuts/');
      const merged: Record<ActionKey, string> = { ...DEFAULT_SHORTCUTS };
      for (const { action_key, shortcut_key } of res.data.shortcuts) {
        if (ACTION_KEYS.includes(action_key as ActionKey)) {
          merged[action_key as ActionKey] = shortcut_key;
        }
      }
      set({ shortcutsMap: merged });
    } catch {
      // keep existing map on error
    }
  },
}));

/**
 * Whether the keystroke is someone typing rather than reaching for a shortcut.
 *
 * The listener is on `window`, so it sees every keystroke in the app including
 * the ones going into an invoice line. A combo carrying Ctrl/Alt/Meta is still
 * honoured there — Ctrl+S from inside a field is the whole point of Ctrl+S —
 * but a bare key is indistinguishable from typing, and a user who remaps an
 * action onto one would otherwise fire it on every matching character.
 */
function isTypingTarget(e: KeyboardEvent): boolean {
  if (e.ctrlKey || e.altKey || e.metaKey) {
    return false;
  }
  const target = e.target as HTMLElement | null;
  if (!target) {
    return false;
  }
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

function normalizeCombo(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey) parts.push('Ctrl');
  if (e.shiftKey) parts.push('Shift');
  if (e.altKey) parts.push('Alt');
  if (e.metaKey) parts.push('Meta');
  const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  parts.push(key);
  return parts.join('+');
}

export function ShortcutsProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const refetchShortcuts = useShortcutsStore((s) => s.refetchShortcuts);

  useEffect(() => {
    if (isAuthenticated) {
      refetchShortcuts();
    }
  }, [isAuthenticated, refetchShortcuts]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e)) return;
      const { shortcutsMap, handlers } = useShortcutsStore.getState();
      const combo = normalizeCombo(e);
      const action = (Object.keys(shortcutsMap) as ActionKey[]).find(
        (k) => shortcutsMap[k] === combo,
      );
      if (!action) return;
      const handler = handlers.get(action);
      if (!handler) return;
      e.preventDefault();
      handler();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return <>{children}</>;
}

export function useShortcuts() {
  return useShortcutsStore(useShallow((s) => ({
    shortcutsMap: s.shortcutsMap,
    shortcutFor: s.shortcutFor,
    registerAction: s.registerAction,
    refetchShortcuts: s.refetchShortcuts,
  })));
}
