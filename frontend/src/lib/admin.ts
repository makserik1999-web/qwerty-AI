/**
 * The admin panel's requests.
 *
 * Nothing here decides who may see what. Every /api/admin route checks the
 * staff role on the server and answers 404 to anyone else; the interface only
 * avoids offering a link that would lead there.
 */
import { ApiError, type PlanSummary } from './api'
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
  /** free | trial | ustaz_month | ustaz_year | paused */
  plan: string
  blocked: boolean
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
  plan_detail: PlanSummary
  blocked_reason: string
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

/* Changing things ------------------------------------------------------------
 * Every call carries a reason: the server refuses without one and writes it
 * into the audit log next to who did it.
 */

async function send<T>(path: string, method: 'POST' | 'PUT', body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/admin${path}`, {
      method,
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, '')
  }
  if (!response.ok) {
    let detail = ''
    let reason = ''
    try {
      const data = await response.json()
      if (data && typeof data.detail === 'string') detail = data.detail
      if (data && typeof data.code === 'string') reason = data.code
    } catch {
      /* the status is all there is */
    }
    throw new ApiError(response.status, detail, reason)
  }
  return (await response.json()) as T
}

const user = (id: string) => `/users/${encodeURIComponent(id)}`

export function grantSubscription(
  id: string,
  body: { plan_id: string; months?: number; until?: string; reason: string },
) {
  return send<{ plan: PlanSummary }>(`${user(id)}/subscription`, 'POST', body)
}

export function endSubscription(id: string, reason: string) {
  return send<{ plan: PlanSummary }>(`${user(id)}/subscription/end`, 'POST', { reason })
}

export function addExtraVideos(id: string, count: number, reason: string) {
  return send<{ plan: PlanSummary }>(`${user(id)}/extra-videos`, 'POST', { count, reason })
}

export function resetTrial(id: string, reason: string) {
  return send<{ ok: boolean }>(`${user(id)}/trial/reset`, 'POST', { reason })
}

export function blockUser(id: string, reason: string) {
  return send<{ ok: boolean }>(`${user(id)}/block`, 'POST', { reason })
}

export function unblockUser(id: string, reason: string) {
  return send<{ ok: boolean }>(`${user(id)}/unblock`, 'POST', { reason })
}

export interface AdminPlan {
  id: string
  kind: 'trial' | 'subscription' | 'addon'
  title: string
  price: number
  period?: 'month' | 'school_year'
  limits?: Record<string, number | null>
  carryover_cap?: number
  max_effort?: 'low' | 'medium' | 'high'
  watermark?: boolean
  docx_signature?: boolean
  videos?: number
}

export function listPlans() {
  return request<{ items: AdminPlan[] }>('/plans')
}

export function editPlan(id: string, changes: Partial<AdminPlan> & { reason: string }) {
  return send<AdminPlan>(`/plans/${encodeURIComponent(id)}`, 'PUT', changes)
}
