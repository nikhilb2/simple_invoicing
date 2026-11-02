import { expect, test } from 'vitest';
import { parseContentDispositionFilename } from './contentDisposition.ts';

test('reads a quoted filename', () => {
  expect(parseContentDispositionFilename('attachment; filename="statement_Acme_2026-01-01_2026-01-31.csv"'))
    .toBe('statement_Acme_2026-01-01_2026-01-31.csv');
});

test('reads an unquoted filename', () => {
  expect(parseContentDispositionFilename('attachment; filename=statement.csv'))
    .toBe('statement.csv');
});

test('decodes an RFC 5987 encoded filename', () => {
  expect(parseContentDispositionFilename("attachment; filename*=UTF-8''statement%20Acme.csv"))
    .toBe('statement Acme.csv');
});

test('prefers the encoded filename when both are present', () => {
  expect(parseContentDispositionFilename('attachment; filename="fallback.csv"; filename*=UTF-8\'\'preferred.csv'))
    .toBe('preferred.csv');
});

test('returns null when there is no filename', () => {
  expect(parseContentDispositionFilename('attachment')).toBe(null);
  expect(parseContentDispositionFilename(null)).toBe(null);
  expect(parseContentDispositionFilename(undefined)).toBe(null);
});

test('strips a path down to its last segment', () => {
  expect(parseContentDispositionFilename('attachment; filename="../secret.csv"'))
    .toBe('secret.csv');
});

test('returns null for a malformed encoded value', () => {
  expect(parseContentDispositionFilename("attachment; filename*=UTF-8''%E0%A4%A"))
    .toBe(null);
});
