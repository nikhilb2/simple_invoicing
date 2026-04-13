import { create } from 'zustand';
import { activateFinancialYear, createFinancialYear, getFinancialYears, type FinancialYear } from '../api/financialYears';

type FYState = {
  fyList: FinancialYear[];
  loading: boolean;
  setFYList: (list: FinancialYear[]) => void;
  clearFYList: () => void;
  refreshFYList: () => Promise<void>;
  switchFY: (id: number) => Promise<void>;
  createFY: (label: string, startDate: string, endDate: string) => Promise<void>;
};

export const useFYStore = create<FYState>((set, get) => ({
  fyList: [],
  loading: false,

  setFYList: (list) => set({ fyList: list }),

  clearFYList: () => set({ fyList: [] }),

  refreshFYList: async () => {
    set({ loading: true });
    try {
      const list = await getFinancialYears();
      set({ fyList: list });
    } catch {
      // Keep existing list on error
    } finally {
      set({ loading: false });
    }
  },

  switchFY: async (id) => {
    const current = get().fyList;
    set({ fyList: current.map((fy) => ({ ...fy, is_active: fy.id === id })) });
    try {
      await activateFinancialYear(id);
      await get().refreshFYList();
    } catch {
      await get().refreshFYList();
    }
  },

  createFY: async (label, startDate, endDate) => {
    await createFinancialYear({ label, start_date: startDate, end_date: endDate });
    await get().refreshFYList();
  },
}));
