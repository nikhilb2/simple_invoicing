/**
 * Reads the filename out of a Content-Disposition header, if one is there.
 *
 * Handles the plain form (`attachment; filename="statement.csv"`), the
 * unquoted form, and the RFC 5987 encoded form
 * (`attachment; filename*=UTF-8''statement%20name.csv`). Returns null when
 * there is no usable filename, so callers can fall back to their own name.
 * A path in the value is stripped to its last segment: a filename that
 * escapes its directory is never a filename the browser should honour.
 */
export function parseContentDispositionFilename(header: string | null | undefined): string | null {
  if (!header) return null;

  const encoded = /filename\*\s*=\s*([^;]+)/i.exec(header);
  if (encoded) {
    const value = encoded[1].trim().replace(/^UTF-8''/i, '');
    try {
      const decoded = decodeURIComponent(value).replace(/\\/g, '/').split('/').pop() ?? '';
      return decoded || null;
    } catch {
      return null;
    }
  }

  const plain = /filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(header);
  if (!plain) return null;
  const value = (plain[1] ?? plain[2]).trim().replace(/\\/g, '/').split('/').pop() ?? '';
  return value || null;
}
