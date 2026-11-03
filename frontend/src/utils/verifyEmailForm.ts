/** Client-side password limits for verify-email (matches backend NewPassword). */
export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 128;
export const MAX_PASSWORD_BYTES = 72;

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
  return null;
}

/**
 * Whether a verify-email failure means the link itself is dead.
 * Only then should the page leave the password form for the resend form.
 */
export function isDeadVerificationLink(errorCode: string | null): boolean {
  return errorCode === 'invalid_token';
}
