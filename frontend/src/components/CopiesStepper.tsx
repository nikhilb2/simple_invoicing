import { Minus, Plus } from 'lucide-react';

const MIN = 1;
const MAX = 10;

type CopiesStepperProps = {
  value: number;
  onChange: (next: number) => void;
};

/**
 * How many copies of the invoice to render.
 *
 * A setting, not an action, which is why it sits above the menu's actions
 * rather than in the button row: changing it refetches the whole preview, and
 * on most invoices it is never touched at all.
 *
 * A stepper rather than a number input on purpose. The range is 1-10, so two
 * buttons beat a keyboard on a phone, and there is no half-typed state to
 * defend against -- the old input let the field go empty mid-edit and had to
 * repair itself on blur.
 */
export default function CopiesStepper({ value, onChange }: CopiesStepperProps) {
  const clamp = (n: number) => Math.min(MAX, Math.max(MIN, n));

  return (
    <div className="copies-stepper" role="group" aria-label="Number of copies">
      <span className="copies-stepper__label">Copies</span>
      <div className="copies-stepper__control">
        <button
          type="button"
          className="copies-stepper__step"
          onClick={() => onChange(clamp(value - 1))}
          disabled={value <= MIN}
          aria-label="One copy fewer"
          title="One copy fewer"
        >
          <Minus size={14} aria-hidden="true" />
        </button>
        <span className="copies-stepper__value" aria-live="polite">{value}</span>
        <button
          type="button"
          className="copies-stepper__step"
          onClick={() => onChange(clamp(value + 1))}
          disabled={value >= MAX}
          aria-label="One copy more"
          title="One copy more"
        >
          <Plus size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
