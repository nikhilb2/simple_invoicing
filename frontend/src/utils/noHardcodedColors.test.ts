import { describe, expect, it } from 'vitest';

// Guard for the light/dark theme (#447): .tsx files must use var(--token)
// colours from styles.css, never hex or rgb()/rgba() literals.
// Sources are read as raw text through Vite (no Node typings in this project).
const sources = import.meta.glob('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

// Paths relative to frontend/src, forward slashes. Keep this list small.
const ALLOWLIST = [
  // Recharts needs concrete colour strings; themed separately in chartTheme.
  'pages/analytics/charts/',
  // Deliberately light, self-contained status pill (dark ink on pale fill),
  // readable on both themes.
  'pages/CreditNotesPage.tsx',
];

const COLOR_LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\((?!var\()/;

// Drop comments so prose like "product #501" is not mistaken for a colour.
function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1');
}

describe('no hard-coded colours in .tsx', () => {
  it('uses var(--token) instead of hex/rgb literals', () => {
    const offenders: string[] = [];
    for (const [path, text] of Object.entries(sources)) {
      const rel = path.replace(/^\/src\//, '');
      if (ALLOWLIST.some((p) => rel === p || (p.endsWith('/') && rel.startsWith(p)))) continue;
      stripComments(text).split('\n').forEach((line, i) => {
        if (COLOR_LITERAL.test(line)) offenders.push(`${rel}:${i + 1}: ${line.trim()}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
