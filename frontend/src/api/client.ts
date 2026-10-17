// Thin wrapper around fetch for the CDP API. Every request goes through here so auth and
// error handling live in one place.

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`/app${path}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.detail ?? response.statusText)
  }
  return response.json() as Promise<T>
}

export type Health = { status: string; database: string; today: string }

export const getHealth = () => apiGet<Health>('/health')
