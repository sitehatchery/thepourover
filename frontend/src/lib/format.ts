// "Today" is fixed by the brief. The API reports it (/app/health); this default matches the server config.
let today = '2026-09-28'

export function setToday(value: string) {
  today = value
}

export function getToday(): string {
  return today
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "Sep 25, 2026", or "Today" for the configured today. Accepts a date or an ISO timestamp. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return ''
  return value.slice(0, 10) === today ? 'Today' : shortDate(value)
}

/** Always the calendar date ("Sep 28, 2026"), even for today. */
export function shortDate(value: string): string {
  const [year, month, date] = value.slice(0, 10).split('-').map(Number)
  return `${MONTHS[month - 1]} ${date}, ${year}`
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : value.toLocaleString('en-US')
}
