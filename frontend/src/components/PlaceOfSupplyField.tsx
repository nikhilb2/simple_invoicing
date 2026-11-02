import { GST_STATES } from '../utils/gstStates';

type Props = {
  id: string;
  value: string;
  onChange: (code: string) => void;
};

/** The state a sale is made in, which decides IGST or CGST + SGST. */
export default function PlaceOfSupplyField({ id, value, onChange }: Props) {
  return (
    <div className="field">
      <label htmlFor={id}>Place of supply</label>
      <select id={id} className="select" value={value} onChange={(event) => onChange(event.target.value)}>
        {value === '' ? <option value="">Choose a state</option> : null}
        {GST_STATES.map((state) => (
          <option key={state.code} value={state.code}>
            {state.code} – {state.name}
          </option>
        ))}
      </select>
    </div>
  );
}
