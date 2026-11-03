import { describe, expect, it } from 'vitest';
import {
  isDeadVerificationLink,
  MAX_PASSWORD_BYTES,
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  passwordClientError,
} from './verifyEmailForm';

describe('passwordClientError', () => {
  it('rejects short passwords', () => {
    expect(passwordClientError('short')).toBe(
      `Password must be at least ${MIN_PASSWORD_LENGTH} characters long`,
    );
  });

  it('rejects passwords longer than the character max', () => {
    expect(passwordClientError('a'.repeat(MAX_PASSWORD_LENGTH + 1))).toBe(
      `Password must be at most ${MAX_PASSWORD_LENGTH} characters long`,
    );
  });

  it('rejects passwords that exceed the bcrypt byte limit', () => {
    // "é" is 2 UTF-8 bytes; 37 of them is 74 bytes with length 37.
    const tooManyBytes = 'é'.repeat(37);
    expect(new TextEncoder().encode(tooManyBytes).length).toBeGreaterThan(MAX_PASSWORD_BYTES);
    expect(passwordClientError(tooManyBytes)).toBe(
      `Password must be at most ${MAX_PASSWORD_BYTES} bytes long`,
    );
  });

  it('accepts a normal password', () => {
    expect(passwordClientError('password1')).toBeNull();
  });
});

describe('isDeadVerificationLink', () => {
  it('treats only invalid_token as a dead link', () => {
    expect(isDeadVerificationLink('invalid_token')).toBe(true);
    expect(isDeadVerificationLink('email_not_verified')).toBe(false);
    expect(isDeadVerificationLink(null)).toBe(false);
  });
});
