import { create } from 'zustand';

const COLLAPSED_KEY = 'sidebar_collapsed';
const OPEN_SECTION_KEY = 'sidebar_open_section';

/** Opened on a first visit, before any route has taught the rail otherwise. */
const DEFAULT_OPEN_SECTION = 'sales';

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === 'true';
  } catch {
    return false;
  }
}

function readOpenSection(): string | null {
  try {
    const stored = localStorage.getItem(OPEN_SECTION_KEY);
    // '' is the stored form of "everything closed", which is distinct from
    // never having chosen — the latter should still open the default.
    if (stored === null) return DEFAULT_OPEN_SECTION;
    return stored === '' ? null : stored;
  } catch {
    return DEFAULT_OPEN_SECTION;
  }
}

function persist(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Private browsing / storage disabled — keep the in-memory state working.
  }
}

type SidebarState = {
  /** Desktop rail mode. The mobile drawer is separate, ephemeral state in Layout. */
  collapsed: boolean;
  toggleCollapsed: () => void;
  /**
   * The one expanded nav section, accordion-style. Holding a single id rather
   * than a set is the whole point: it is what keeps the rail to roughly ten
   * rows however many sections exist.
   */
  openSection: string | null;
  /** Collapses the section if it is already the open one. */
  toggleSection: (id: string) => void;
  /** Used to follow the route; a no-op when that section is already open. */
  openSectionFor: (id: string) => void;
};

/**
 * localStorage is read in the initializers rather than an effect so a collapsed
 * rail doesn't flash open, and a closed section doesn't flash expanded, on
 * first paint.
 *
 * Persistence is hand-rolled to match the house style — useAuthStore and
 * api/client.ts do the same; nothing here uses zustand's persist middleware.
 */
export const useSidebarStore = create<SidebarState>((set) => ({
  collapsed: readCollapsed(),
  toggleCollapsed: () =>
    set((state) => {
      const collapsed = !state.collapsed;
      persist(COLLAPSED_KEY, String(collapsed));
      return { collapsed };
    }),

  openSection: readOpenSection(),
  toggleSection: (id) =>
    set((state) => {
      const openSection = state.openSection === id ? null : id;
      persist(OPEN_SECTION_KEY, openSection ?? '');
      return { openSection };
    }),
  openSectionFor: (id) =>
    set((state) => {
      if (state.openSection === id) return state;
      persist(OPEN_SECTION_KEY, id);
      return { openSection: id };
    }),
}));
