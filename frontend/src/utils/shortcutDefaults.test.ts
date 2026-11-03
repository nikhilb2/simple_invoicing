import { describe, expect, test } from 'vitest';
import {
  ACTION_KEYS,
  ACTION_LABELS,
  DEFAULT_SHORTCUTS,
  type ActionKey,
} from './shortcutDefaults';

describe('shortcutDefaults — invariant protection across action keys', () => {
  test('every action key in ACTION_KEYS has a default shortcut', () => {
    for (const key of ACTION_KEYS) {
      expect(DEFAULT_SHORTCUTS[key]).toBeDefined();
      expect(typeof DEFAULT_SHORTCUTS[key]).toBe('string');
      expect(DEFAULT_SHORTCUTS[key].trim().length).toBeGreaterThan(0);
    }
  });

  test('every action key in ACTION_KEYS has a descriptive label', () => {
    for (const key of ACTION_KEYS) {
      expect(ACTION_LABELS[key]).toBeDefined();
      expect(typeof ACTION_LABELS[key]).toBe('string');
      expect(ACTION_LABELS[key].trim().length).toBeGreaterThan(0);
    }
  });

  test('DEFAULT_SHORTCUTS contains only keys defined in ACTION_KEYS', () => {
    const definedKeys = new Set(ACTION_KEYS);
    for (const key of Object.keys(DEFAULT_SHORTCUTS)) {
      expect(definedKeys.has(key as ActionKey)).toBe(true);
    }
  });

  test('ACTION_LABELS contains only keys defined in ACTION_KEYS', () => {
    const definedKeys = new Set(ACTION_KEYS);
    for (const key of Object.keys(ACTION_LABELS)) {
      expect(definedKeys.has(key as ActionKey)).toBe(true);
    }
  });
});

describe('shortcutDefaults — uniqueness invariant', () => {
  test('no two actions share the same default key combination', () => {
    const seen = new Map<string, string>();
    const duplicates: Array<{ key1: string; key2: string; shortcut: string }> = [];

    for (const key of ACTION_KEYS) {
      const shortcut = DEFAULT_SHORTCUTS[key];
      if (seen.has(shortcut)) {
        duplicates.push({
          key1: seen.get(shortcut)!,
          key2: key,
          shortcut,
        });
      } else {
        seen.set(shortcut, key);
      }
    }

    expect(duplicates).toEqual([]);
    const uniqueShortcuts = new Set(Object.values(DEFAULT_SHORTCUTS));
    expect(uniqueShortcuts.size).toBe(ACTION_KEYS.length);
  });
});
