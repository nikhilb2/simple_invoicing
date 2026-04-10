import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { activateFinancialYear, createFinancialYear, getFinancialYears, type FinancialYear } from '../api/financialYears';
import { useAuth } from './AuthContext';

type FYContextType = {
  activeFY: FinancialYear | null;
  fyList: FinancialYear[];
  loading: boolean;
  switchFY: (id: number) => Promise<void>;
  createFY: (label: string, startDate: string, endDate: string) => Promise<void>;
  refreshFYList: () => Promise<void>;
};

const FYContext = createContext<FYContextType | undefined>(undefined);

export function FYProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [fyList, setFyList] = useState<FinancialYear[]>([]);
  const [loading, setLoading] = useState(false);

  const refreshFYList = useCallback(async () => {
    setLoading(true);
    try {
      const list = await getFinancialYears();
      setFyList(list);
    } catch {
      // leave existing list on error
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      refreshFYList();
    } else {
      setFyList([]);
    }
  }, [isAuthenticated, refreshFYList]);

  const activeFY = useMemo(
    () => fyList.find((fy) => fy.is_active) ?? null,
    [fyList],
  );

  const switchFY = useCallback(async (id: number) => {
    // Optimistic update
    setFyList((prev) =>
      prev.map((fy) => ({ ...fy, is_active: fy.id === id })),
    );
    try {
      await activateFinancialYear(id);
      await refreshFYList();
    } catch {
      // Roll back optimistic update
      await refreshFYList();
    }
  }, [refreshFYList]);

  const createFY = useCallback(
    async (label: string, startDate: string, endDate: string) => {
      await createFinancialYear({ label, start_date: startDate, end_date: endDate });
      await refreshFYList();
    },
    [refreshFYList],
  );

  const value = useMemo(
    () => ({ activeFY, fyList, loading, switchFY, createFY, refreshFYList }),
    [activeFY, fyList, loading, switchFY, createFY, refreshFYList],
  );

  return <FYContext.Provider value={value}>{children}</FYContext.Provider>;
}

export function useFY(): FYContextType {
  const ctx = useContext(FYContext);
  if (!ctx) throw new Error('useFY must be used inside <FYProvider>');
  return ctx;
}
