import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import PasswordInput from './PasswordInput';

describe('PasswordInput', () => {
  it('starts masked, with a Show password toggle that is not pressed', () => {
    const html = renderToString(
      <PasswordInput
        id="password"
        placeholder="Enter password"
        value=""
        onChange={() => {}}
        autoComplete="current-password"
      />,
    );

    expect(html).toContain('type="password"');
    expect(html).toContain('aria-label="Show password"');
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain('type="button"');
  });

  it('keeps the caller supplied id, class and autoComplete', () => {
    const html = renderToString(
      <PasswordInput
        id="smtp-password"
        className="input"
        value=""
        onChange={() => {}}
        autoComplete="new-password"
      />,
    );

    expect(html).toContain('id="smtp-password"');
    expect(html).toContain('class="input"');
    expect(html).toContain('autoComplete="new-password"');
  });
});
