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
  web_active_days: number
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

export type SegmentFilter = {
  field: string
  operator: string
  value?: string | number | boolean | string[] | null
  within_last_days?: number | null
}

export type SegmentDefinition = { match: 'all' | 'any'; filters: SegmentFilter[] }

export type Segment = SegmentSummary & {
  definition: SegmentDefinition
  created_at: string | null
  updated_at: string | null
}

export type FieldSpec = {
  type: 'string' | 'number' | 'date' | 'boolean' | 'activity'
  label: string
  description: string
  category: string
  operators: string[]
  values?: string[]
  supports_within_last_days?: boolean
}

export type SegmentSchema = { today: string; fields: Record<string, FieldSpec> }

export type ImportRun = {
  import_run_id: number
  status: 'running' | 'succeeded' | 'failed'
  source: string
  message: string
  file_stats: Record<string, { entity: string; read: number; loaded: number; fixed: number; rejected: number; duplicates_merged: number }>
  has_error_report: boolean
  started_at: string
  finished_at: string | null
}

export type CurrentUser = { kind: string; id: number; name: string; is_admin: boolean }

export type WebhookCall = {
  webhook_call_id: number
  received_at: string
  channel: 'webhook' | 'app'
  outcome: 'stored' | 'duplicate' | 'rejected'
  http_status: number
  event_id: string | null
  event: string | null
  app_user_id: string | null
  device_id: string | null
  steps: string[]
  duration_ms: number
}
