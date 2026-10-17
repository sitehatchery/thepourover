import type { SegmentSummary } from '../api/types'

const GROUP_LABELS: Record<SegmentSummary['group'], string> = {
  subscriber: 'Subscribers',
  app_users: 'App users',
  web_events: 'Web events',
}

type Props = {
  segments: SegmentSummary[]
  selected: string[]
  onChange: (slugs: string[]) => void
}

/** Dropdown grouped by segment group; picked segments show as removable tags. */
export default function SegmentPicker({ segments, selected, onChange }: Props) {
  const available = segments.filter((s) => !selected.includes(s.slug))
  const groups = (Object.keys(GROUP_LABELS) as SegmentSummary['group'][])
    .map((group) => ({ group, items: available.filter((s) => s.group === group) }))
    .filter((g) => g.items.length)
  const name = (slug: string) => segments.find((s) => s.slug === slug)?.name ?? slug

  return (
    <div className="segment-picker">
      <label className="field">
        Segments
        <select
          className="input"
          value=""
          onChange={(e) => e.target.value && onChange([...selected, e.target.value])}
        >
          <option value="">Add a segment…</option>
          {groups.map(({ group, items }) => (
            <optgroup key={group} label={GROUP_LABELS[group]}>
              {items.map((s) => (
                <option key={s.slug} value={s.slug} title={s.summary}>
                  {s.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {selected.length > 0 && (
        <ul className="tags" aria-label="Selected segments">
          {selected.map((slug) => (
            <li key={slug} className="tag">
              {name(slug)}
              <button
                type="button"
                className="tag-remove"
                aria-label={`Remove ${name(slug)}`}
                onClick={() => onChange(selected.filter((s) => s !== slug))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
