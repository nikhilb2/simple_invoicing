import { useMemo } from 'react';
import { buildRangePresets, matchPreset, type DateRange } from '../utils/dateRanges';

/**
 * One-click ranges beside the two date inputs. A reporting range is almost
 * never typed twice — it is "this month", "last month", "the financial year" —
 * so the common ones become a chip and the inputs are left for the range that
 * is genuinely custom.
 */
export default function DateRangePresets({
  value,
  onChange,
  fy,
  label = 'Range',
}: {
  value: DateRange;
  onChange: (range: DateRange) => void;
  fy?: { start_date: string; end_date: string } | null;
  label?: string;
}) {
  // Rebuilt only when the financial year changes; "today" moving under a page
  // that is already open is not a case worth a timer.
  const presets = useMemo(() => buildRangePresets(fy), [fy]);
  const active = matchPreset(presets, value);

  return (
    <div className="scope-presets" role="group" aria-label={`${label} presets`}>
      {presets.map((preset) => (
        <button
          key={preset.key}
          type="button"
          className={`scope-preset${active === preset.key ? ' scope-preset--on' : ''}`}
          aria-pressed={active === preset.key}
          onClick={() => onChange({ fromDate: preset.fromDate, toDate: preset.toDate })}
        >
          {preset.label}
        </button>
      ))}
    </div>
  );
}
