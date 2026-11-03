import { describe, expect, it } from 'vitest';
import { deriveIsAdmin } from './authRole';

describe('deriveIsAdmin', () => {
  it('treats the creator of a company as admin although the global role is staff', () => {
    expect(deriveIsAdmin('admin', 'staff')).toBe(true);
  });

  it('lets the company role demote a globally admin user', () => {
    expect(deriveIsAdmin('staff', 'admin')).toBe(false);
  });

  it('falls back to the global role when no company role is known', () => {
    expect(deriveIsAdmin(null, 'admin')).toBe(true);
    expect(deriveIsAdmin(undefined, 'staff')).toBe(false);
  });

  it('is false before /auth/me has answered', () => {
    expect(deriveIsAdmin(null, null)).toBe(false);
  });
});
