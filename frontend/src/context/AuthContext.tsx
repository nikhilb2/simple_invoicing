import { useEffect } from 'react';
import { useShallow } from 'zustand/shallow';
import type { AuthToken, UserProfile } from '../types/api';
import { deriveIsAdmin } from '../utils/authRole';
import { useAuthStore } from '../store/useAuthStore';

type AuthContextType = {
  token: string | null;
  userEmail: string | null;
  userRole: UserProfile['role'] | null;
  companyRole: UserProfile['role'] | null;
  /** Admin of the active company (not necessarily of the platform). */
  isAdmin: boolean;
  /** Runs the deployment itself: SMTP, backups. See require_platform_admin. */
  canManagePlatform: boolean;
  isAuthenticated: boolean;
  setSession: (tokens: AuthToken) => Promise<void>;
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
    companyRole: s.companyRole,
    canManagePlatform: s.canManagePlatform,
    setSession: s.setSession,
    login: s.login,
    logout: s.logout,
  })));

  return {
    ...state,
    isAdmin: deriveIsAdmin(state.companyRole, state.userRole),
    isAuthenticated: Boolean(state.token),
  } as AuthContextType;
}
