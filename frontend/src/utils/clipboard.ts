/** Copies on insecure HTTP origins where the async clipboard API is unavailable. */
function copyViaSelection(text: string): boolean {
  if (typeof document === 'undefined' || !document.body || typeof document.execCommand !== 'function') {
    return false;
  }

  let field: HTMLTextAreaElement | null = null;
  try {
    field = document.createElement('textarea');
    field.value = text;
    field.setAttribute('readonly', '');
    field.style.position = 'fixed';
    field.style.opacity = '0';
    document.body.appendChild(field);
    field.select();
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    if (field?.parentNode) field.parentNode.removeChild(field);
  }
}

/** Tries the async Clipboard API first, then falls back to selecting text. */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Permission denial or unsupported contexts can still use selection copy.
  }

  return copyViaSelection(text);
}
