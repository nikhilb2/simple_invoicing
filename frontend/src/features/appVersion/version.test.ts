import { describe, expect, it } from 'vitest';
import { parseVersionPayload, shouldPromptReload } from './version';

describe('parseVersionPayload', () => {
  it('reads the version out of a well-formed payload', () => {
    expect(parseVersionPayload('{"version":"2026-08-27T10:14:03.221Z"}')).toBe(
      '2026-08-27T10:14:03.221Z',
    );
  });

  it('tolerates the trailing newline the build writes', () => {
    expect(parseVersionPayload('{"version":"abc123"}\n')).toBe('abc123');
  });

  it('returns null for an index.html body from an SPA fallback', () => {
    expect(parseVersionPayload('<!doctype html>\n<html lang="en">')).toBeNull();
  });

  it('returns null for truncated JSON', () => {
    expect(parseVersionPayload('{"version":"2026-08-2')).toBeNull();
  });

  it('returns null when the version key is missing, blank, or not a string', () => {
    expect(parseVersionPayload('{}')).toBeNull();
    expect(parseVersionPayload('{"version":"   "}')).toBeNull();
    expect(parseVersionPayload('{"version":123}')).toBeNull();
    expect(parseVersionPayload('null')).toBeNull();
    expect(parseVersionPayload('"2026-08-27"')).toBeNull();
  });
});

describe('shouldPromptReload', () => {
  it('stays quiet when the server is serving this same build', () => {
    expect(shouldPromptReload('v1', 'v1', null)).toBe(false);
  });

  it('prompts when the server has moved on', () => {
    expect(shouldPromptReload('v1', 'v2', null)).toBe(true);
  });

  it('stays quiet when the stamp could not be read', () => {
    expect(shouldPromptReload('v1', null, null)).toBe(false);
  });

  it('stays quiet for a version the user already dismissed', () => {
    expect(shouldPromptReload('v1', 'v2', 'v2')).toBe(false);
  });

  it('prompts again once a later deploy lands', () => {
    expect(shouldPromptReload('v1', 'v3', 'v2')).toBe(true);
  });

  it('prompts on a rollback, not just on a newer build', () => {
    expect(shouldPromptReload('2026-08-27T10:00:00Z', '2026-08-26T09:00:00Z', null)).toBe(true);
  });
});
