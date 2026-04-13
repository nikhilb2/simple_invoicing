import { create } from 'zustand';
import api from '../api/client';
import type { AuthToken, UserProfile } from '../types/api';

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

type AuthState = {
  token: string | null;
  userEmail: string | null;
  userRole: UserProfile['role'] | null;
  setToken: (token: string | null) => void;
  setUserRole: (role: UserProfile['role'] | null) => void;
  hydrateUserRole: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem('token'),
  userEmail: decodeEmailFromToken(localStorage.getItem('token')),
  userRole: null,

  setToken: (token) => {
    set({ token, userEmail: decodeEmailFromToken(token) });
  },

  setUserRole: (role) => {
    set({ userRole: role });
  },

  hydrateUserRole: async () => {
    const token = get().token;
    if (!token) {
      set({ userRole: null });
      return;
    }

    try {
      const res = await api.get<UserProfile>('/auth/me');
      set({ userRole: res.data.role });
    } catch {
      set({ userRole: null });
    }
  },

  login: async (email: string, password: string) => {
    const res = await api.post<AuthToken>('/auth/login', { email, password });
    localStorage.setItem('token', res.data.access_token);
    localStorage.setItem('refresh_token', res.data.refresh_token);
    set({
      token: res.data.access_token,
      userEmail: decodeEmailFromToken(res.data.access_token),
    });
    await get().hydrateUserRole();
  },

  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('refresh_token');
    set({ token: null, userEmail: null, userRole: null });
  },
}));
