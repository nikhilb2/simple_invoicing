/**
 * SearchInput.tsx
 *
 * A shared controlled search box with a one click clear button, used
 * wherever a page previously re-implemented its own search input.
 *
 * The clear button only renders while the box has text, so an empty box
 * shows no dead control. Clearing goes through the caller's onChange with
 * an empty string, exactly as if the text had been deleted by typing, so
 * it triggers the same debounce and reload behaviour the page already
 * has. Pressing Escape does the same. The button is a native button with
 * an aria-label, so it works with mouse, keyboard and screen readers, and
 * never submits a surrounding form (type="button").
 *
 * The look stays with the caller: each page passes the class names its
 * search box already used, so migrating a page changes no styling.
 * Callers hide the browser's native search cancel button in their own
 * CSS (as the Ledgers page already did) so there is only one clear
 * button, not two overlapping glyphs.
 */
import type { KeyboardEvent } from 'react';
import { Search, X } from 'lucide-react';

type SearchInputProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Screen reader only label text, rendered as a label for the input. */
  label: string;
  /** Wrapper class, e.g. the page's existing search wrapper class. */
  wrapperClassName: string;
  /** Input class, e.g. "input ledger-search__input". Defaults to "input". */
  inputClassName?: string;
  /** Search icon class, e.g. the page's existing search icon class. */
  iconClassName?: string;
  /** Clear button class, e.g. the page's existing clear button class. */
  clearClassName?: string;
  /** Accessible name (and title) of the clear button. */
  clearLabel?: string;
};

export default function SearchInput({
  id,
  value,
  onChange,
  placeholder,
  label,
  wrapperClassName,
  inputClassName = 'input',
  iconClassName,
  clearClassName,
  clearLabel = 'Clear search',
}: SearchInputProps) {
  function clear() {
    if (value) {
      onChange('');
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      clear();
    }
  }

  return (
    <div className={wrapperClassName}>
      <label className="sr-only" htmlFor={id}>
        {label}
      </label>
      <Search size={16} className={iconClassName} aria-hidden="true" />
      <input
        id={id}
        className={inputClassName}
        type="search"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      {value ? (
        <button
          type="button"
          className={clearClassName}
          onClick={clear}
          title={clearLabel}
          aria-label={clearLabel}
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
