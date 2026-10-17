import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { apiGet, apiSend } from '../api/client'
import type { FieldSpec, Segment, SegmentDefinition, SegmentFilter, SegmentSchema } from '../api/types'
import { countOf } from '../lib/format'
import './SegmentEditorPage.css'
import './TablePage.css'

const OPERATOR_LABELS: Record<string, string> = {
  equals: 'is',
  not_equals: 'is not',
  in: 'is any of',
  not_in: 'is none of',
  is_empty: 'is empty',
  is_not_empty: 'has a value',
  gte: 'is at least',
  lte: 'is at most',
  before: 'is before',
  after: 'is after',
  on: 'is on',
  within_last_days: 'is in the last',
  not_within_last_days: 'is not in the last',
  includes: 'includes',
  not_includes: 'does not include',
}

const NO_VALUE = new Set(['is_empty', 'is_not_empty'])
const DAY_OPERATORS = new Set(['within_last_days', 'not_within_last_days'])
const GROUPS = [
  { value: 'subscriber', label: 'Subscribers' },
  { value: 'app_users', label: 'App users' },
  { value: 'web_events', label: 'Website visitors' },
]

type Preview = { key: string; count?: number; summary?: string; error?: string }

/** A sensible starting value when the field or operator changes. */
function defaultValue(spec: FieldSpec, operator: string): SegmentFilter['value'] {
  if (NO_VALUE.has(operator)) return null
  if (DAY_OPERATORS.has(operator)) return 30
  if (spec.type === 'boolean') return true
  if (spec.type === 'number') return 1
  if (spec.type === 'date') return ''
  if (operator === 'in' || operator === 'not_in') return []
  return spec.values?.[0] ?? ''
}

function isComplete(filter: SegmentFilter): boolean {
  if (NO_VALUE.has(filter.operator)) return true
  const v = filter.value
  if (Array.isArray(v)) return v.length > 0
  return v !== '' && v !== null && v !== undefined && !(typeof v === 'number' && Number.isNaN(v))
}

function clean(definition: SegmentDefinition): SegmentDefinition {
  return {
    match: definition.match,
    filters: definition.filters.map(({ field, operator, value, within_last_days }) => ({
      field,
      operator,
      ...(NO_VALUE.has(operator) ? {} : { value }),
      ...(within_last_days ? { within_last_days } : {}),
    })),
  }
}

export default function SegmentEditorPage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const [schema, setSchema] = useState<SegmentSchema | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [group, setGroup] = useState('subscriber')
  const [definition, setDefinition] = useState<SegmentDefinition>({ match: 'all', filters: [] })
  const [loaded, setLoaded] = useState(!slug)
  const [preview, setPreview] = useState<Preview>({ key: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<SegmentSchema>('/segments/schema').then(setSchema).catch((err: Error) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!slug) return
    apiGet<Segment>(`/segments/${slug}`)
      .then((s) => {
        setName(s.name)
        setDescription(s.description)
        setGroup(s.group)
        setDefinition(s.definition)
        setLoaded(true)
      })
      .catch((err: Error) => setError(err.message))
  }, [slug])

  const complete = definition.filters.every(isComplete)
  const previewKey = JSON.stringify(clean(definition))

  // Live count as the definition changes (debounced).
  useEffect(() => {
    if (!loaded || !complete) return
    const timer = setTimeout(() => {
      apiSend<{ member_count: number; summary: string }>('POST', '/segments/preview', JSON.parse(previewKey))
        .then((r) => setPreview({ key: previewKey, count: r.member_count, summary: r.summary }))
        .catch((err: Error) => setPreview({ key: previewKey, error: err.message }))
    }, 350)
    return () => clearTimeout(timer)
  }, [previewKey, complete, loaded])

  const fieldsByCategory = useMemo(() => {
    const map = new Map<string, [string, FieldSpec][]>()
    for (const entry of Object.entries(schema?.fields ?? {})) {
      const list = map.get(entry[1].category) ?? []
      list.push(entry)
      map.set(entry[1].category, list)
    }
    return [...map.entries()]
  }, [schema])

  function setFilter(index: number, changes: Partial<SegmentFilter>) {
    setDefinition((d) => ({ ...d, filters: d.filters.map((f, i) => (i === index ? { ...f, ...changes } : f)) }))
  }

  function changeField(index: number, field: string) {
    const spec = schema!.fields[field]
    const operator = spec.operators[0]
    setFilter(index, { field, operator, value: defaultValue(spec, operator), within_last_days: null })
  }

  function changeOperator(index: number, operator: string) {
    const filter = definition.filters[index]
    const spec = schema!.fields[filter.field]
    const keepValue = !NO_VALUE.has(operator) && DAY_OPERATORS.has(operator) === DAY_OPERATORS.has(filter.operator)
      && (operator === 'in' || operator === 'not_in') === Array.isArray(filter.value)
    setFilter(index, { operator, value: keepValue ? filter.value : defaultValue(spec, operator) })
  }

  function addFilter() {
    const field = 'acquisition_source'
    const spec = schema!.fields[field]
    setDefinition((d) => ({ ...d, filters: [...d.filters, { field, operator: 'equals', value: defaultValue(spec, 'equals') }] }))
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const body = { name: name.trim(), description: description.trim(), group, definition: clean(definition) }
      const saved = slug
        ? await apiSend<Segment>('PUT', `/segments/${slug}`, body)
        : await apiSend<Segment>('POST', '/segments', body)
      navigate(`/segments/${saved.slug}`)
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  const current = preview.key === previewKey ? preview : null

  return (
    <section className="table-page">
      <div className="page-head">
        <div>
          <p className="crumb">
            <Link to="/segments">Segments</Link> /
          </p>
          <h1>{slug ? 'Edit segment' : 'New segment'}</h1>
        </div>
      </div>

      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}

      {schema && loaded && (
        <form className="editor" onSubmit={save}>
          <div className="editor-main">
            <div className="editor-card">
              <div className="editor-meta">
                <label className="field">
                  Name
                  <input className="input" value={name} maxLength={64} required onChange={(e) => setName(e.target.value)} />
                </label>
                <label className="field">
                  Group
                  <select className="input" value={group} onChange={(e) => setGroup(e.target.value)}>
                    {GROUPS.map((g) => (
                      <option key={g.value} value={g.value}>
                        {g.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field span-all">
                  Description (optional)
                  <input
                    className="input"
                    value={description}
                    maxLength={500}
                    placeholder="What this group means, in plain English"
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </label>
              </div>
            </div>

            <div className="editor-card">
              <div className="match-row">
                People who match
                <select
                  className="input match-select"
                  value={definition.match}
                  onChange={(e) => setDefinition({ ...definition, match: e.target.value as 'all' | 'any' })}
                >
                  <option value="all">all</option>
                  <option value="any">any</option>
                </select>
                of these rules:
              </div>

              {definition.filters.length === 0 && (
                <p className="muted">No rules yet, so this segment includes everyone. Add a rule to narrow it down.</p>
              )}

              <ol className="rules">
                {definition.filters.map((filter, i) => {
                  const spec = schema.fields[filter.field]
                  return (
                    <li key={i} className={isComplete(filter) ? 'rule' : 'rule incomplete'}>
                      <select
                        className="input rule-field"
                        aria-label="Field"
                        value={filter.field}
                        onChange={(e) => changeField(i, e.target.value)}
                      >
                        {fieldsByCategory.map(([category, fields]) => (
                          <optgroup key={category} label={category}>
                            {fields.map(([key, f]) => (
                              <option key={key} value={key} title={f.description}>
                                {f.label}
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                      <select
                        className="input rule-operator"
                        aria-label="Condition"
                        value={filter.operator}
                        onChange={(e) => changeOperator(i, e.target.value)}
                      >
                        {spec.operators.map((op) => (
                          <option key={op} value={op}>
                            {OPERATOR_LABELS[op] ?? op}
                          </option>
                        ))}
                      </select>
                      <ValueEditor spec={spec} filter={filter} onChange={(changes) => setFilter(i, changes)} />
                      <button
                        type="button"
                        className="btn btn-ghost rule-remove"
                        aria-label="Remove rule"
                        onClick={() => setDefinition({ ...definition, filters: definition.filters.filter((_, j) => j !== i) })}
                      >
                        ×
                      </button>
                      <p className="rule-help">{spec.description}</p>
                    </li>
                  )
                })}
              </ol>

              <button type="button" className="btn" onClick={addFilter} disabled={definition.filters.length >= 20}>
                + Add rule
              </button>
            </div>
          </div>

          <aside className="editor-side">
            <div className="preview-card" aria-live="polite">
              <p className="preview-label">Matches right now</p>
              <p className="preview-count">
                {!complete ? '–' : current?.count !== undefined ? countOf(current.count, 'person', 'people') : '…'}
              </p>
              <p className="preview-summary">
                {!complete ? 'Finish each rule to see a count.' : current?.error ? current.error : current?.summary}
              </p>
            </div>
            <button className="btn btn-primary save-btn" disabled={saving || !name.trim() || !complete || Boolean(current?.error)}>
              {saving ? 'Saving…' : slug ? 'Save changes' : 'Save segment'}
            </button>
            <Link className="btn btn-ghost" to={slug ? `/segments/${slug}` : '/segments'}>
              Cancel
            </Link>
          </aside>
        </form>
      )}
    </section>
  )
}

type ValueProps = { spec: FieldSpec; filter: SegmentFilter; onChange: (changes: Partial<SegmentFilter>) => void }

function ValueEditor({ spec, filter, onChange }: ValueProps) {
  const { operator, value } = filter
  if (NO_VALUE.has(operator)) return <span className="rule-value" />

  if (DAY_OPERATORS.has(operator)) {
    return (
      <span className="rule-value days">
        <input
          className="input"
          type="number"
          min={1}
          max={3650}
          aria-label="Days"
          value={typeof value === 'number' ? value : ''}
          onChange={(e) => onChange({ value: e.target.value === '' ? '' : Number(e.target.value) })}
        />
        days
      </span>
    )
  }

  if (spec.type === 'boolean') {
    return (
      <select className="input rule-value" aria-label="Value" value={String(value)} onChange={(e) => onChange({ value: e.target.value === 'true' })}>
        <option value="true">yes</option>
        <option value="false">no</option>
      </select>
    )
  }

  if (spec.type === 'number') {
    return (
      <input
        className="input rule-value"
        type="number"
        min={0}
        aria-label="Value"
        value={typeof value === 'number' ? value : ''}
        onChange={(e) => onChange({ value: e.target.value === '' ? '' : Number(e.target.value) })}
      />
    )
  }

  if (spec.type === 'date') {
    return (
      <input
        className="input rule-value"
        type="date"
        aria-label="Date"
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange({ value: e.target.value })}
      />
    )
  }

  if (operator === 'in' || operator === 'not_in') {
    const selected = Array.isArray(value) ? value : []
    return (
      <span className="rule-value checks" role="group" aria-label="Values">
        {(spec.values ?? []).map((v) => (
          <label key={v} className={selected.includes(v) ? 'check on' : 'check'}>
            <input
              type="checkbox"
              checked={selected.includes(v)}
              onChange={(e) => onChange({ value: e.target.checked ? [...selected, v] : selected.filter((s) => s !== v) })}
            />
            {v}
          </label>
        ))}
      </span>
    )
  }

  const choice = spec.values?.length ? (
    <select className="input" aria-label="Value" value={String(value ?? '')} onChange={(e) => onChange({ value: e.target.value })}>
      {spec.values.map((v) => (
        <option key={v}>{v}</option>
      ))}
    </select>
  ) : (
    <input className="input" aria-label="Value" value={String(value ?? '')} onChange={(e) => onChange({ value: e.target.value })} />
  )

  if (spec.type === 'activity') {
    return (
      <span className="rule-value activity">
        {choice}
        <label className="within">
          within
          <input
            className="input"
            type="number"
            min={1}
            max={3650}
            placeholder="any"
            aria-label="Within the last N days (optional)"
            value={filter.within_last_days ?? ''}
            onChange={(e) => onChange({ within_last_days: e.target.value ? Number(e.target.value) : null })}
          />
          days
        </label>
      </span>
    )
  }
  return <span className="rule-value">{choice}</span>
}
