import api from './client';
import type { AuthConfig, AuthToken, DetailResponse, RegisterRequest, UserProfile } from '../types/api';

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const res = await api.get<AuthConfig>('/auth/config');
  return res.data;
}

export async function registerAccount(payload: RegisterRequest): Promise<DetailResponse> {
  const res = await api.post<DetailResponse>('/auth/register', payload);
  return res.data;
}

export async function verifyEmail(token: string, newPassword: string, fullName: string): Promise<DetailResponse> {
  const res = await api.post<DetailResponse>('/auth/verify-email', {
    token, new_password: newPassword, full_name: fullName,
  });
  return res.data;
}

export async function resendVerification(email: string): Promise<DetailResponse> {
  const res = await api.post<DetailResponse>('/auth/resend-verification', { email });
  return res.data;
}

export async function forgotPassword(email: string): Promise<DetailResponse> {
  const res = await api.post<DetailResponse>('/auth/forgot-password', { email });
  return res.data;
}

export async function resetPassword(token: string, newPassword: string): Promise<DetailResponse> {
  const res = await api.post<DetailResponse>('/auth/reset-password', { token, new_password: newPassword });
  return res.data;
}

export async function exchangeOAuthCode(code: string): Promise<AuthToken> {
  const res = await api.post<AuthToken>(
    '/auth/oauth/exchange',
    { code },
    // The si_oauth_state cookie set during the Google redirect binds the code
    // to this browser. Same-origin /api sends it anyway; a cross-origin
    // VITE_API_BASE_URL only does with this set.
    { withCredentials: true },
  );
  return res.data;
}

export async function fetchMe(): Promise<UserProfile> {
  const res = await api.get<UserProfile>('/auth/me');
  return res.data;
}
