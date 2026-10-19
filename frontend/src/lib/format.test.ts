import { describe, expect, it } from 'vitest'
import { countOf, dateRangeInvalid, formatDate, shortDate } from './format'
import { differsFromApplied } from './useListQuery'

describe('format', () => {
  it('shows the configured today as "Today" and other dates in full', () => {
    expect(formatDate('2026-09-28T10:00:00')).toBe('Today')
    expect(formatDate('2026-09-25')).toBe('Sep 25, 2026')
    expect(shortDate('2026-09-28')).toBe('Sep 28, 2026')
    expect(formatDate(null)).toBe('')
  })

  it('pluralizes counts', () => {
    expect(countOf(1, 'person', 'people')).toBe('1 person')
    expect(countOf(2900, 'person', 'people')).toBe('2,900 people')
    expect(countOf(2, 'web event')).toBe('2 web events')
  })

  it('rejects a date range that ends before it starts', () => {
    expect(dateRangeInvalid('2026-09-10', '2026-09-01')).toBe(true)
    expect(dateRangeInvalid('2026-09-01', '2026-09-10')).toBe(false)
    expect(dateRangeInvalid('2026-09-01', '')).toBe(false)
  })
})

describe('differsFromApplied (enables Apply filters only after a change)', () => {
  const applied = new URLSearchParams('event=login&segment_id=a&segment_id=b&anonymous=true')

  it('is false when the form matches the URL, ignoring order and padding', () => {
    expect(differsFromApplied({ event: ' login ', segment_id: ['b', 'a'], anonymous: true, email: '' }, applied)).toBe(false)
  })

  it('is true when any value changed', () => {
    expect(differsFromApplied({ event: 'app_open', segment_id: ['a', 'b'], anonymous: true }, applied)).toBe(true)
    expect(differsFromApplied({ event: 'login', segment_id: ['a'], anonymous: true }, applied)).toBe(true)
    expect(differsFromApplied({ event: 'login', segment_id: ['a', 'b'], anonymous: false }, applied)).toBe(true)
    expect(differsFromApplied({ event: 'login', segment_id: ['a', 'b'], anonymous: true, email: 'gmail' }, applied)).toBe(true)
  })
})
