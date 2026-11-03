import { placeOfSupplyOptions } from '../utils/gstStates';

type Props = {
  id: string;
  value: string;
  onChange: (code: string) => void;
  warning?: string | null;
};

/** The state a sale is made in, which decides IGST or CGST + SGST. */
export default function PlaceOfSupplyField({ id, value, onChange, warning }: Props) {
  return (
    <div className="field">
      <label htmlFor={id}>Place of supply</label>
      <select id={id} className="select" value={value} onChange={(event) => onChange(event.target.value)}>
        {value === '' ? <option value="">Choose a state</option> : null}
        {placeOfSupplyOptions(value).map((state) => (
          <option key={state.code} value={state.code}>
            {state.code} – {state.name}
          </option>
        ))}
      </select>
      {warning ? <p className="field-warning" role="alert">{warning}</p> : null}
    </div>
  );
}
