import type { AuthToken, VerifyEmailResponse } from '../types/api';

/** Client-side password limits for verify-email (matches backend NewPassword). */
export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 128;
export const MAX_PASSWORD_BYTES = 72;

export const COMMON_PASSWORD_MESSAGE =
  'This password is too common and easy to guess. Choose a less obvious one, such as three unrelated words.';

// Mirrors COMMON_PASSWORDS in backend/src/schemas/auth.py, which is what enforces it.
const COMMON_PASSWORDS = new Set([
  '00000000', '11111111', '11223344', '12341234', '12344321', '12345678',
  '123456789', '1234567890', '87654321', '1q2w3e4r', '1qaz2wsx',
  'abc12345', 'abc@1234', 'abc@12345', 'abcd1234', 'abcd@1234', 'abcdefgh',
  'admin123', 'admin1234', 'admin@123', 'administrator', 'asdfasdf', 'asdfghjk',
  'baseball', 'changeme', 'football', 'iloveyou', 'india123', 'india@123',
  'letmein1', 'letmein123', 'p@ssw0rd', 'p@ssword', 'passw0rd', 'password',
  'password1', 'password12', 'password123', 'password1234', 'password@1',
  'password@123', 'princess', 'qwerty12', 'qwerty123', 'qwerty@123', 'qwertyui',
  'qwertyuiop', 'sunshine', 'superman', 'test1234', 'test@123', 'trustno1',
  'welcome1', 'welcome123', 'welcome@123',
]);

export function isCommonPassword(password: string): boolean {
  return COMMON_PASSWORDS.has(password.toLowerCase());
}

/** Local validation message, or null when the password is fine to submit. */
export function passwordClientError(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters long`;
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return `Password must be at most ${MAX_PASSWORD_LENGTH} characters long`;
  }
  const bytes = new TextEncoder().encode(password).length;
  if (bytes > MAX_PASSWORD_BYTES) {
    return `Password must be at most ${MAX_PASSWORD_BYTES} bytes long`;
  }
  if (isCommonPassword(password)) {
    return COMMON_PASSWORD_MESSAGE;
  }
  return null;
}

/** The session to start after verifying, or null when this browser has to sign in itself. */
export function verifiedSession(res: VerifyEmailResponse): AuthToken | null {
  if (!res.access_token || !res.refresh_token) return null;
  return { access_token: res.access_token, refresh_token: res.refresh_token, token_type: res.token_type ?? 'bearer' };
}

/**
 * Whether a verify-email failure means the link itself is dead.
 * Only then should the page leave the password form for the resend form.
 */
export function isDeadVerificationLink(errorCode: string | null): boolean {
  return errorCode === 'invalid_token';
}
