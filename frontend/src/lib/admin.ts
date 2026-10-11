/**
 * The admin panel's requests.
 *
 * Nothing here decides who may see what. Every /api/admin route checks the
 * staff role on the server and answers 404 to anyone else; the interface only
 * avoids offering a link that would lead there.
 */
import { ApiError } from './api'
import type { Role, StaffRole } from './types'

export interface Usage {
  explanations: number
  videos: number
  from_library: number
  failed: number
  assessments: number
  lesson_plans: number
  quiz_drafts: number
  quizzes: number
}

export interface AdminUser {
  id: string
  email: string
  name: string
  username: string
  role: Role
  staff_role: StaffRole | null
  created_at: string | null
  email_verified: boolean
  phone: string | null
  phone_verified: boolean
  google: boolean
  usage: Usage
}

export interface UsageEntry {
  at: string | null
  kind: 'explanation' | 'assessment' | 'lesson_plan' | 'quiz_draft'
  ok: boolean
  video: boolean
  cached: boolean
}

export interface AdminUserDetail extends AdminUser {
  last_sign_in: string | null
  quota: {
    used_hour: number
    used_day: number
    limit_hour: number
    limit_day: number
  }
  recent: UsageEntry[]
}

export interface StatsDay extends Usage {
  date: string
  signups: number
}

export interface Stats {
  totals: { users: number; teachers: number; staff: number }
  usage_logged_since: string | null
  utc_offset_hours: number
  agent: { connected: boolean; queue: number }
  days: StatsDay[]
}

export interface AuditEntry {
  id: string
  at: string | null
  actor: { kind: 'staff' | 'server'; user_id: string; email: string; role: string }
  action: string
  target: { user_id?: string; email?: string }
  details: Record<string, unknown>
  reason: string
}

export interface CacheStats {
  entries_by_tier: Record<string, number>
  entries_total: number
  questions_seen: number
  questions_repeated: number
  top_questions: Array<{ question: string; hits: number }>
}

async function request<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/admin${path}`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new ApiError(0, '')
  }
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      /* the status is all there is */
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

export function listUsers(q: string, skip: number, limit = 50) {
  const params = new URLSearchParams({ q, skip: String(skip), limit: String(limit) })
  return request<{ total: number; items: AdminUser[] }>(`/users?${params}`)
}

export function getUser(id: string) {
  return request<AdminUserDetail>(`/users/${encodeURIComponent(id)}`)
}

export function getStats(days: number) {
  return request<Stats>(`/stats?days=${days}`)
}

export function getAudit(skip = 0, limit = 50) {
  return request<{ items: AuditEntry[] }>(`/audit?skip=${skip}&limit=${limit}`)
}

export function getCacheStats() {
  return request<CacheStats>('/cache/stats')
}
