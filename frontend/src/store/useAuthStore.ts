import { create } from 'zustand';
import api from '../api/client';
import { identifyUser, resetAnalyticsUser } from '../lib/analytics';
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
      if (typeof res.data.active_company_id === 'number') {
        localStorage.setItem('active_company_id', String(res.data.active_company_id));
      } else {
        localStorage.removeItem('active_company_id');
      }
      set({ userRole: res.data.role });
    } catch {
      set({ userRole: null });
    }
  },

  login: async (email: string, password: string) => {
    const res = await api.post<AuthToken>('/auth/login', { email, password });
    localStorage.setItem('token', res.data.access_token);
    localStorage.setItem('refresh_token', res.data.refresh_token);
    const identifiedEmail = decodeEmailFromToken(res.data.access_token);
    set({
      token: res.data.access_token,
      userEmail: identifiedEmail,
    });

    // The one piece of analytics the browser still owns. Events are captured
    // server-side and keyed by this same email, so identifying here is what puts
    // the recording of a session and the events that session produced on one
    // person instead of two. Role and active company are set on the person by
    // the backend, on login and on every company switch.
    if (identifiedEmail) {
      identifyUser(identifiedEmail, { email: identifiedEmail });
    }

    await get().hydrateUserRole();
  },

  logout: () => {
    // Fire-and-forget, and before the token is cleared: the endpoint exists so
    // that signing out is counted on the server like every other event. Nothing
    // waits on it and a failure is not worth surfacing -- the sign-out itself is
    // local, and happens either way.
    void api.post('/auth/logout').catch(() => undefined);
    resetAnalyticsUser();
    localStorage.removeItem('token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('active_company_id');
    set({ token: null, userEmail: null, userRole: null });
  },
}));
