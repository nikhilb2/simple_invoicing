import { useThemeStore, type ThemePreference } from '../store/useThemeStore';

const OPTIONS: { value: ThemePreference; label: string; hint: string }[] = [
  { value: 'system', label: 'System', hint: 'Follow your device setting' },
  { value: 'light', label: 'Light', hint: 'Always use the light theme' },
  { value: 'dark', label: 'Dark', hint: 'Always use the dark theme' },
];

export default function AppearancePage() {
  const preference = useThemeStore((s) => s.preference);
  const setPreference = useThemeStore((s) => s.setPreference);

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page-title">Appearance</h1>
          <p className="section-copy">
            Choose how Simple Invoicing looks. The choice is saved in this browser only.
          </p>
        </div>
      </section>

      <section className="panel stack">
        <fieldset className="appearance-fieldset">
          <legend className="eyebrow">Theme</legend>
          <div className="appearance-options">
            {OPTIONS.map((option) => {
              const id = `theme-${option.value}`;
              const selected = preference === option.value;
              return (
                <label
                  key={option.value}
                  htmlFor={id}
                  className={`appearance-option${selected ? ' appearance-option--selected' : ''}`}
                >
                  {/* Swatches picture each theme, so they keep their own colours in either theme. */}
                  <span className={`appearance-swatch appearance-swatch--${option.value}`} aria-hidden="true">
                    <span className="appearance-swatch__bar" />
                    <span className="appearance-swatch__line" />
                    <span className="appearance-swatch__line appearance-swatch__line--short" />
                  </span>
                  <span className="appearance-option__row">
                    <input
                      type="radio"
                      id={id}
                      name="theme"
                      value={option.value}
                      checked={selected}
                      onChange={() => setPreference(option.value)}
                    />
                    <span>
                      <strong className="appearance-option__label">{option.label}</strong>
                      <span className="appearance-option__hint">{option.hint}</span>
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
      </section>
    </div>
  );
}
