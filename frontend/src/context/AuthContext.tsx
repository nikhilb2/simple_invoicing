import { useEffect } from 'react';
import { useShallow } from 'zustand/shallow';
import type { UserProfile } from '../types/api';
import { useAuthStore } from '../store/useAuthStore';

type AuthContextType = {
  token: string | null;
  userEmail: string | null;
  userRole: UserProfile['role'] | null;
  isAdmin: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { token, hydrateUserRole, setUserRole } = useAuthStore(useShallow((s) => ({
    token: s.token,
    hydrateUserRole: s.hydrateUserRole,
    setUserRole: s.setUserRole,
  })));

  useEffect(() => {
    if (!token) {
      setUserRole(null);
      return;
    }
    void hydrateUserRole();
  }, [token, hydrateUserRole, setUserRole]);

  return <>{children}</>;
}

export function useAuth() {
  const state = useAuthStore(useShallow((s) => ({
    token: s.token,
    userEmail: s.userEmail,
    userRole: s.userRole,
    login: s.login,
    logout: s.logout,
  })));

  return {
    ...state,
    isAdmin: state.userRole === 'admin',
    isAuthenticated: Boolean(state.token),
  } as AuthContextType;
}
