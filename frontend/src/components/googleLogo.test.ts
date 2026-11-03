import { describe, expect, it } from 'vitest';

// A .ts file because noHardcodedColors.test.ts, rightly, refuses these values in .tsx.
const files = import.meta.glob('/public/google-g.svg', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('Google logo', () => {
  it("keeps the four colours Google's branding rules require", () => {
    const svg = files['/public/google-g.svg'];

    for (const colour of ['#EA4335', '#4285F4', '#FBBC05', '#34A853']) {
      expect(svg).toContain(colour);
    }
  });
});
