// Every API call goes through here, so auth and errors are handled in one place.
// The access token lives only in memory; the refresh token is an httpOnly cookie the page can't read.

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let accessToken: string | null = null
let onSignedOut: () => void = () => {}
let refreshing: Promise<boolean> | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function onSessionEnded(handler: () => void) {
  onSignedOut = handler
}

type TokenResponse = { access_token: string; expires_in: number }

/** Swap the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch('/app/auth/refresh', { method: 'POST', credentials: 'same-origin' })
    .then(async (response) => {
      if (!response.ok) return false
      setAccessToken(((await response.json()) as TokenResponse).access_token)
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

async function errorMessage(response: Response): Promise<string> {
  const body = await response.json().catch(() => ({}))
  const detail = body.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join('; ')
  return response.statusText || 'Request failed'
}

async function request(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)

  const response = await fetch(`/app${path}`, { ...init, headers, credentials: 'same-origin' })
  if (response.status === 401 && retry && !path.startsWith('/auth/')) {
    if (await refreshSession()) return request(path, init, false)
    setAccessToken(null)
    onSignedOut()
  }
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  return response
}

export async function apiGet<T>(path: string): Promise<T> {
  return (await request(path)).json() as Promise<T>
}

export async function apiSend<T>(method: 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const response = await request(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return (response.status === 204 ? undefined : await response.json()) as T
}

/** Download a CSV through fetch (so the auth header is sent) and hand it to the browser as a file. */
export async function downloadCsv(path: string, fallbackName: string): Promise<void> {
  const response = await request(path)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName
  const url = URL.createObjectURL(await response.blob())
  const link = Object.assign(document.createElement('a'), { href: url, download: name })
  link.click()
  URL.revokeObjectURL(url)
}

/** Build a query string, skipping empty values and repeating array values (e.g. segment_id). */
export function query(params: Record<string, string | number | boolean | string[] | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '' || value === false) continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v))
    else search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
