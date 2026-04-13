import { useEffect, useMemo } from 'react';
import { useShallow } from 'zustand/shallow';
import type { FinancialYear } from '../api/financialYears';
import { useAuth } from './AuthContext';
import { useFYStore } from '../store/useFYStore';

type FYContextType = {
  activeFY: FinancialYear | null;
  fyList: FinancialYear[];
  loading: boolean;
  switchFY: (id: number) => Promise<void>;
  createFY: (label: string, startDate: string, endDate: string) => Promise<void>;
  refreshFYList: () => Promise<void>;
};

export function FYProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const { refreshFYList, clearFYList } = useFYStore(useShallow((s) => ({
    refreshFYList: s.refreshFYList,
    clearFYList: s.clearFYList,
  })));

  useEffect(() => {
    if (isAuthenticated) {
      void refreshFYList();
    } else {
      clearFYList();
    }
  }, [isAuthenticated, refreshFYList, clearFYList]);

  return <>{children}</>;
}

export function useFY(): FYContextType {
  const { fyList, loading, switchFY, createFY, refreshFYList } = useFYStore(
    useShallow((s) => ({
      fyList: s.fyList,
      loading: s.loading,
      switchFY: s.switchFY,
      createFY: s.createFY,
      refreshFYList: s.refreshFYList,
    })),
  );

  const activeFY = useMemo(
    () => fyList.find((fy) => fy.is_active) ?? null,
    [fyList],
  );

  return {
    activeFY,
    fyList,
    loading,
    switchFY,
    createFY,
    refreshFYList,
  };
}
