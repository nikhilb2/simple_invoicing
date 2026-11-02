import { expect, test } from 'vitest';
import { downloadCsv, escapeCsvCell, toCsv } from './csv.ts';

test('renders headers and rows with plain values', () => {
  expect(toCsv(['Customer', 'Total'], [['Acme', 1500]])).toBe('Customer,Total\r\nAcme,1500');
});

test('renders an empty row set as headers only', () => {
  expect(toCsv(['Customer', 'Total'], [])).toBe('Customer,Total');
});

test('renders null and undefined cells as empty', () => {
  expect(escapeCsvCell(null)).toBe('');
  expect(escapeCsvCell(undefined)).toBe('');
  expect(toCsv(['Due date'], [[null]])).toBe('Due date\r\n');
});

test('quotes cells with commas and doubles embedded quotes', () => {
  expect(toCsv(['Customer'], [['Acme, Ltd']])).toBe('Customer\r\n"Acme, Ltd"');
  expect(toCsv(['Customer'], [['Say "hi"']])).toBe('Customer\r\n"Say ""hi"""');
});

test('quotes cells with newlines', () => {
  expect(toCsv(['Customer'], [['Line one\nLine two']])).toBe('Customer\r\n"Line one\nLine two"');
});

test.each(['=2+2', '+123', '-5', '@SUM(A1:A2)'])(
  'prefixes formula looking values with a single quote: %s',
  (value) => {
    expect(escapeCsvCell(value)).toBe(`'${value}`);
  },
);

test('still quotes a formula looking value that also holds a comma', () => {
  expect(escapeCsvCell('=A1,B1')).toBe('"\'=A1,B1"');
});

test('leaves numbers untouched, including negatives', () => {
  expect(escapeCsvCell(-250)).toBe('-250');
  expect(escapeCsvCell(0)).toBe('0');
});

test('downloadCsv writes a BOM prefixed CSV blob and clicks a download link', async () => {
  const created: Blob[] = [];
  const realCreateObjectURL = URL.createObjectURL;
  const realRevokeObjectURL = URL.revokeObjectURL;
  const realDocument = (globalThis as { document?: unknown }).document;
  let revoked: string | null = null;
  let clicked: { href: string; download: string } | null = null;
  const link = {
    href: '',
    download: '',
    click() {
      clicked = { href: this.href, download: this.download };
    },
    remove() {},
  };
  (globalThis as { document: unknown }).document = {
    createElement: () => link,
    body: { appendChild: () => {} },
  };
  URL.createObjectURL = ((blob: Blob) => {
    created.push(blob);
    return 'blob:test';
  }) as typeof URL.createObjectURL;
  URL.revokeObjectURL = ((url: string) => {
    revoked = url;
  }) as typeof URL.revokeObjectURL;
  try {
    downloadCsv('invoice_dues_2026-10-29.csv', ['Customer', 'Total'], [['Acme', 1500]]);
    expect(created).toHaveLength(1);
    expect(created[0]?.type).toBe('text/csv;charset=utf-8');
    // Blob.text() strips a leading BOM, so check the raw bytes instead:
    // EF BB BF followed by the CSV text.
    const bytes = new Uint8Array(await created[0]!.arrayBuffer());
    expect(Array.from(bytes.slice(0, 3))).toEqual([0xef, 0xbb, 0xbf]);
    expect(new TextDecoder().decode(bytes.slice(3))).toBe('Customer,Total\r\nAcme,1500');
    expect(clicked).toEqual({ href: 'blob:test', download: 'invoice_dues_2026-10-29.csv' });
    expect(revoked).toBe('blob:test');
  } finally {
    URL.createObjectURL = realCreateObjectURL;
    URL.revokeObjectURL = realRevokeObjectURL;
    (globalThis as { document?: unknown }).document = realDocument;
  }
});
