import { useQuery } from '@tanstack/react-query';
import { fetchAuthConfig } from '../api/auth';
import type { AuthConfig } from '../types/api';

/** What a deployment has switched off. Everything is hidden until the answer arrives, or if it fails. */
const NOTHING_ENABLED: AuthConfig = { password_signup_enabled: false, password_reset_enabled: false, providers: [] };

export function useAuthConfig(): AuthConfig & { isLoading: boolean } {
  const query = useQuery({
    queryKey: ['auth-config'],
    queryFn: fetchAuthConfig,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  return { ...(query.data ?? NOTHING_ENABLED), isLoading: query.isLoading };
}
