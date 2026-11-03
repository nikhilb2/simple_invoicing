import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import SearchInput from './SearchInput';

describe('SearchInput', () => {
  it('shows no clear button while the box is empty', () => {
    const html = renderToString(
      <SearchInput
        id="ledger-search"
        wrapperClassName="ledger-search"
        inputClassName="input ledger-search__input"
        iconClassName="ledger-search__icon"
        clearClassName="ledger-search__clear"
        label="Search ledgers by name"
        placeholder="Search ledgers by name, GST or contact..."
        value=""
        onChange={() => {}}
      />,
    );

    expect(html).toContain('type="search"');
    expect(html).toContain('id="ledger-search"');
    expect(html).toContain('Search ledgers by name');
    expect(html).not.toContain('Clear search');
    expect(html).not.toContain('type="button"');
  });

  it('shows a labelled clear button only once the box has text', () => {
    const html = renderToString(
      <SearchInput
        id="catalogue-search"
        wrapperClassName="catalogue-search"
        inputClassName="input catalogue-search__input"
        iconClassName="catalogue-search__icon"
        clearClassName="catalogue-search__clear"
        label="Search the catalogue"
        placeholder="Search by name, SKU or serial..."
        value="bolt"
        onChange={() => {}}
      />,
    );

    expect(html).toContain('type="button"');
    expect(html).toContain('aria-label="Clear search"');
    expect(html).toContain('title="Clear search"');
  });

  it('keeps the caller supplied wrapper, input, icon and clear classes', () => {
    const html = renderToString(
      <SearchInput
        id="catalogue-search"
        wrapperClassName="catalogue-search"
        inputClassName="input catalogue-search__input"
        iconClassName="catalogue-search__icon"
        clearClassName="catalogue-search__clear"
        label="Search the catalogue"
        value="bolt"
        onChange={() => {}}
      />,
    );

    expect(html).toContain('class="catalogue-search"');
    expect(html).toContain('class="input catalogue-search__input"');
    expect(html).toContain('catalogue-search__icon');
    expect(html).toContain('class="catalogue-search__clear"');
  });
});
