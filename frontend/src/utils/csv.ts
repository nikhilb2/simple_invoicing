/**
 * Shared browser side CSV export.
 *
 * Built for the Invoice Dues page and meant to be reused by any other
 * page that exports rows it already loaded, for example the credit
 * notes and email history export. Callers pass plain headers and rows;
 * this module owns quoting, the formula injection guard, the UTF-8
 * BOM, and the download itself, so no page reimplements them.
 */

export type CsvValue = string | number | null | undefined;

/** Characters that make a spreadsheet treat a cell as a formula. */
const FORMULA_STARTS = new Set(['=', '+', '-', '@']);

/**
 * Renders one cell as CSV text: empty for null or undefined, plain
 * for numbers, and quoted (with doubled quotes) when the text holds
 * a comma, a quote, or a line break. A text cell starting with a
 * formula character gets a leading single quote so a spreadsheet
 * shows it as text instead of running it.
 */
export function escapeCsvCell(value: CsvValue): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return String(value);
  let text = value;
  if (text.length > 0 && FORMULA_STARTS.has(text.charAt(0))) {
    text = `'${text}`;
  }
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

/** Builds CSV text from headers and rows, one row per line. */
export function toCsv(headers: string[], rows: CsvValue[][]): string {
  return [headers, ...rows]
    .map((row) => row.map((cell) => escapeCsvCell(cell)).join(','))
    .join('\r\n');
}

/**
 * Downloads CSV text as a file. The UTF-8 BOM keeps Excel and
 * Google Sheets opening non ASCII text correctly. The anchor is
 * added to the document because Firefox ignores clicks on anchors
 * that are not in the document, and the object URL is revoked after.
 */
export function downloadCsv(filename: string, headers: string[], rows: CsvValue[][]): void {
  const blob = new Blob(['\ufeff', toCsv(headers, rows)], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
