import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import api from '../api/client';
import type { AuthToken, UserProfile } from '../types/api';

type AuthContextType = {
  token: string | null;
  userEmail: string | null;
  userRole: UserProfile['role'] | null;
  isAdmin: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function decodeEmailFromToken(token: string | null) {
  if (!token) {
    return null;
  }

  try {
    const [, payload] = token.split('.');
    const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
    return typeof decoded.sub === 'string' ? decoded.sub : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [userEmail, setUserEmail] = useState<string | null>(() => decodeEmailFromToken(localStorage.getItem('token')));
  const [userRole, setUserRole] = useState<UserProfile['role'] | null>(null);

  useEffect(() => {
    setUserEmail(decodeEmailFromToken(token));
  }, [token]);

  useEffect(() => {
    if (!token) {
      setUserRole(null);
      return;
    }
    api.get<UserProfile>('/auth/me').then((res) => {
      setUserRole(res.data.role);
    }).catch(() => {
      setUserRole(null);
    });
  }, [token]);

  const value = useMemo(
    () => ({
      token,
      userEmail,
      userRole,
      isAdmin: userRole === 'admin',
      isAuthenticated: Boolean(token),
      login: async (email: string, password: string) => {
        const res = await api.post<AuthToken>('/auth/login', { email, password });
        localStorage.setItem('token', res.data.access_token);
        localStorage.setItem('refresh_token', res.data.refresh_token);
        setToken(res.data.access_token);
      },
      logout: () => {
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        setToken(null);
        setUserEmail(null);
        setUserRole(null);
      },
    }),
    [token, userEmail, userRole]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
