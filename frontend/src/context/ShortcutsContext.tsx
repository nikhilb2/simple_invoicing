import { useEffect } from 'react';
import { create } from 'zustand';
import { useShallow } from 'zustand/shallow';
import api from '../api/client';
import { useAuth } from './AuthContext';
import { ACTION_KEYS, DEFAULT_SHORTCUTS, type ActionKey } from '../utils/shortcutDefaults';
import { isTypingTarget, normalizeCombo } from '../utils/keyboard';

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
