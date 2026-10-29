type KeyEventLike = Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'shiftKey' | 'altKey' | 'metaKey' | 'target'>;

/**
 * Whether the keystroke is someone typing rather than reaching for a shortcut.
 *
 * The listener is on `window`, so it sees every keystroke in the app including
 * the ones going into an invoice line. A combo carrying Ctrl/Alt/Meta is still
 * honoured there — Ctrl+S from inside a field is the whole point of Ctrl+S —
 * but a bare key is indistinguishable from typing, and a user who remaps an
 * action onto one would otherwise fire it on every matching character.
 */
export function isTypingTarget(e: KeyEventLike): boolean {
  if (e.ctrlKey || e.altKey || e.metaKey) {
    return false;
  }
  const target = e.target as HTMLElement | null;
  if (!target) {
    return false;
  }
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

/** The shortcut string a keystroke is stored and matched as, e.g. `Ctrl+Shift+C`. */
export function normalizeCombo(e: KeyEventLike): string {
  const parts: string[] = [];
  if (e.ctrlKey) parts.push('Ctrl');
  if (e.shiftKey) parts.push('Shift');
  if (e.altKey) parts.push('Alt');
  if (e.metaKey) parts.push('Meta');
  const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  parts.push(key);
  return parts.join('+');
}

/**
 * Whether the keystroke should open the shortcut cheat sheet.
 *
 * Matches on the produced character rather than Shift+/, so it works on
 * layouts where `?` sits elsewhere. A bare `?` while typing is just a question
 * mark, and if the user has bound an action to the same combo, the action wins.
 */
export function isCheatSheetKey(e: KeyEventLike, boundCombos: Iterable<string>): boolean {
  if (e.key !== '?' || e.ctrlKey || e.altKey || e.metaKey) {
    return false;
  }
  if (isTypingTarget(e)) {
    return false;
  }
  const combo = normalizeCombo(e);
  for (const bound of boundCombos) {
    if (bound === combo) return false;
  }
  return true;
}
