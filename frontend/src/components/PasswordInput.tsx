/**
 * PasswordInput.tsx
 *
 * A shared password field with a show/hide toggle, used wherever a plain
 * password input previously had no way to reveal what was typed.
 *
 * The toggle is a native button, so it works with mouse and keyboard and
 * never submits its surrounding form (type="button"). It carries an
 * aria-label that follows the current state and an aria-pressed value, so
 * assistive technology reports whether the password is currently visible.
 * The input keeps whatever className and autoComplete the caller passes,
 * defaulting to the existing "input" class.
 */
import { useState } from 'react';
import type { InputHTMLAttributes } from 'react';
import { Eye, EyeOff } from 'lucide-react';

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>;

export default function PasswordInput({ className = 'input', ...inputProps }: PasswordInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="password-input-wrap">
      <input
        {...inputProps}
        className={className}
        type={visible ? 'text' : 'password'}
      />
      <button
        type="button"
        className="password-input-wrap__toggle"
        onClick={() => setVisible((value) => !value)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
      >
        {visible ? <EyeOff size={18} /> : <Eye size={18} />}
      </button>
    </div>
  );
}
