import { create } from 'zustand';

const STORAGE_KEY = 'sidebar_collapsed';

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

type SidebarState = {
  /** Desktop rail mode. The mobile drawer is separate, ephemeral state in Layout. */
  collapsed: boolean;
  toggleCollapsed: () => void;
};

/**
 * localStorage is read in the initializer rather than an effect so a collapsed
 * rail doesn't flash open on first paint.
 *
 * Persistence is hand-rolled to match the house style — useAuthStore and
 * api/client.ts do the same; nothing here uses zustand's persist middleware.
 */
export const useSidebarStore = create<SidebarState>((set) => ({
  collapsed: readCollapsed(),
  toggleCollapsed: () =>
    set((state) => {
      const collapsed = !state.collapsed;
      try {
        localStorage.setItem(STORAGE_KEY, String(collapsed));
      } catch {
        // Private browsing / storage disabled — keep the in-memory toggle working.
      }
      return { collapsed };
    }),
}));
