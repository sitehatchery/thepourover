import { dateRangeInvalid, getToday } from '../lib/format'

type Props = {
  legend: string
  from: string
  to: string
  onChange: (from: string, to: string) => void
}

export default function DateRange({ legend, from, to, onChange }: Props) {
  return (
    <fieldset className="field date-range">
      <legend>{legend}</legend>
      <div className="date-inputs">
        <input
          className="input"
          type="date"
          aria-label={`${legend} from`}
          value={from}
          max={getToday()}
          onChange={(e) => onChange(e.target.value, to)}
        />
        <span aria-hidden="true">–</span>
        <input
          className="input"
          type="date"
          aria-label={`${legend} to`}
          value={to}
          max={getToday()}
          onChange={(e) => onChange(from, e.target.value)}
        />
      </div>
      {dateRangeInvalid(from, to) && <span className="error-text">The start date must be on or before the end date</span>}
    </fieldset>
  )
}
