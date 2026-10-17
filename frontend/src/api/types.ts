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

export type Profile = Person & {
  newsletter: {
    email: string
    status: 'active' | 'unsubscribed' | null
    signup_date: string | null
    acquisition_source: string | null
    last_open_date: string | null
  } | null
  app_accounts: { app_user_id: string; created_at: string | null; is_placeholder: boolean }[]
  device_ids: string[]
  visitor_ids: string[]
  web_active_days: number
  last_web_visit: string | null
  last_app_activity: string | null
  segments: { segment_id: number; slug: string; name: string }[]
}

export type WebEventRow = {
  web_event_id: number
  email: string | null
  email_backfilled: boolean
  visitor_id: string
  page: string
  timestamp: string
  utm_source: string | null
  profile_id: string | null
}

export type AppEventRow = {
  event_id: string
  event: string
  email: string | null
  user_id: string | null
  device_id: string
  timestamp: string
  received_at: string
  properties: string
  profile_id: string | null
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
