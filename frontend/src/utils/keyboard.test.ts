import { describe, expect, test } from 'vitest';
import { isCheatSheetKey, isTypingTarget, normalizeCombo } from './keyboard';
import { DEFAULT_SHORTCUTS } from './shortcutDefaults';

type Target = { tagName: string; isContentEditable?: boolean } | null;

function key(
  value: string,
  { target = { tagName: 'BODY' } as Target, ctrl = false, shift = false, alt = false, meta = false } = {},
) {
  return {
    key: value,
    ctrlKey: ctrl,
    shiftKey: shift,
    altKey: alt,
    metaKey: meta,
    // A real element always answers isContentEditable with a boolean.
    target: (target && { isContentEditable: false, ...target }) as unknown as EventTarget,
  };
}

const defaults = Object.values(DEFAULT_SHORTCUTS);

describe('normalizeCombo', () => {
  test('orders modifiers Ctrl, Shift, Alt, Meta and upper-cases a single character', () => {
    expect(normalizeCombo(key('c', { ctrl: true, shift: true }))).toBe('Ctrl+Shift+C');
    expect(normalizeCombo(key('i', { alt: true }))).toBe('Alt+I');
    expect(normalizeCombo(key('k', { meta: true, alt: true, shift: true, ctrl: true }))).toBe('Ctrl+Shift+Alt+Meta+K');
  });

  test('keeps named keys as they are', () => {
    expect(normalizeCombo(key('Escape'))).toBe('Escape');
    expect(normalizeCombo(key('F2', { shift: true }))).toBe('Shift+F2');
  });

  test('reports ? as Shift+?, the way the browser delivers it', () => {
    expect(normalizeCombo(key('?', { shift: true }))).toBe('Shift+?');
  });
});

describe('isTypingTarget', () => {
  test.each(['INPUT', 'TEXTAREA', 'SELECT'])('a bare key in %s is typing', (tagName) => {
    expect(isTypingTarget(key('a', { target: { tagName } }))).toBe(true);
  });

  test('a bare key in a contenteditable element is typing', () => {
    expect(isTypingTarget(key('a', { target: { tagName: 'DIV', isContentEditable: true } }))).toBe(true);
  });

  test('a combo with Ctrl, Alt or Meta is a shortcut even inside a field', () => {
    const target = { tagName: 'INPUT' };
    expect(isTypingTarget(key('s', { target, ctrl: true }))).toBe(false);
    expect(isTypingTarget(key('i', { target, alt: true }))).toBe(false);
    expect(isTypingTarget(key('s', { target, meta: true }))).toBe(false);
  });

  test('Shift alone does not make it a shortcut', () => {
    expect(isTypingTarget(key('A', { target: { tagName: 'INPUT' }, shift: true }))).toBe(true);
  });

  test('keys outside a field, or with no target, are not typing', () => {
    expect(isTypingTarget(key('a', { target: { tagName: 'BUTTON' } }))).toBe(false);
    expect(isTypingTarget(key('a', { target: null }))).toBe(false);
  });
});

describe('isCheatSheetKey', () => {
  test('? on the page opens the cheat sheet', () => {
    expect(isCheatSheetKey(key('?', { shift: true }), defaults)).toBe(true);
  });

  test('? without Shift (a layout where it is unshifted) opens it too', () => {
    expect(isCheatSheetKey(key('?'), defaults)).toBe(true);
  });

  test('Shift+/ that does not produce ? on this layout does not', () => {
    expect(isCheatSheetKey(key('/', { shift: true }), defaults)).toBe(false);
  });

  test.each(['INPUT', 'TEXTAREA', 'SELECT'])('? typed into a %s is just a character', (tagName) => {
    expect(isCheatSheetKey(key('?', { target: { tagName }, shift: true }), defaults)).toBe(false);
  });

  test('? typed into a contenteditable element is just a character', () => {
    const target = { tagName: 'DIV', isContentEditable: true };
    expect(isCheatSheetKey(key('?', { target, shift: true }), defaults)).toBe(false);
  });

  test('? with Ctrl, Alt or Meta is some other shortcut', () => {
    expect(isCheatSheetKey(key('?', { shift: true, ctrl: true }), defaults)).toBe(false);
    expect(isCheatSheetKey(key('?', { shift: true, alt: true }), defaults)).toBe(false);
    expect(isCheatSheetKey(key('?', { shift: true, meta: true }), defaults)).toBe(false);
  });

  test('an action the user bound to Shift+? keeps the key', () => {
    expect(isCheatSheetKey(key('?', { shift: true }), [...defaults, 'Shift+?'])).toBe(false);
  });

  test('other keys never open it', () => {
    expect(isCheatSheetKey(key('h'), defaults)).toBe(false);
    expect(isCheatSheetKey(key('F1'), defaults)).toBe(false);
  });
});
