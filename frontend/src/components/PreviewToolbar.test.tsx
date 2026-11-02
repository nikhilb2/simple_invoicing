import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import PreviewToolbar from './PreviewToolbar';

describe('PreviewToolbar title adornment', () => {
  test('renders a keyboard-accessible copy control beside the title', () => {
    const html = renderToStaticMarkup(
      <PreviewToolbar
        eyebrow="Invoice preview"
        title="Invoice INV-0007"
        titleId="invoice-preview-title"
        titleAdornment={<button type="button" title="Copy invoice number" aria-label="Copy invoice number">Copy</button>}
        primary={{ label: 'Share', icon: <span />, onClick: () => {} }}
        onClose={() => {}}
        closeLabel="Close invoice preview"
      />,
    );

    expect(html).toMatch(/preview-header__heading-row[\s\S]*<h2[^>]*>Invoice INV-0007<\/h2>[\s\S]*<button[^>]*aria-label="Copy invoice number"/);
  });

  test('keeps the existing heading markup without an adornment', () => {
    const html = renderToStaticMarkup(
      <PreviewToolbar
        eyebrow="Receipt preview"
        title="Receipt R-007"
        titleId="receipt-preview-title"
        primary={{ label: 'Share', icon: <span />, onClick: () => {} }}
        onClose={() => {}}
        closeLabel="Close receipt preview"
      />,
    );

    expect(html).toContain('<h2 id="receipt-preview-title" class="nav-panel__title">Receipt R-007</h2>');
    expect(html).not.toContain('preview-header__heading-row');
  });
});
