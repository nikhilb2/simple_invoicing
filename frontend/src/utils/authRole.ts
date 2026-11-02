import type { UserProfile } from '../types/api';

/** The company role wins; the global role is the fallback until /auth/me reports one. */
export function deriveIsAdmin(
  companyRole: UserProfile['role'] | null | undefined,
  userRole: UserProfile['role'] | null | undefined,
): boolean {
  return (companyRole ?? userRole) === 'admin';
}
