export type Page<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type Person = {
  profile_id: string
  email: string | null
  signup_date: string | null
  status: 'active' | 'unsubscribed' | null
  acquisition_source: string | null
  last_open_date: string | null
  app_user_id: string | null
  app_created_at: string | null
  app_event_count: number
  web_event_count: number
  last_seen: string | null
  first_utm_source: string | null
  is_subscriber: boolean
  is_placeholder: boolean
}

export type SegmentSummary = {
  segment_id: number
  slug: string
  name: string
  group: 'subscriber' | 'app_users' | 'web_events'
  description: string
  summary: string
  member_count: number | null
}

export type CurrentUser = { kind: string; id: number; name: string; is_admin: boolean }
