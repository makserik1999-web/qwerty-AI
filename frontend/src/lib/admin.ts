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

export function changeRole(id: string, role: Role, reason: string) {
  return send<{ ok: boolean; role: Role }>(`${user(id)}/role`, 'POST', { role, reason })
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
  /** Carry-over caps for everything but videos; null takes one away. */
  carryover_caps?: Record<string, number | null>
  /** Fair-use ceilings on unlimited resources; null takes one away. */
  fair_use?: Record<string, number | null>
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

/* Payments ------------------------------------------------------------------ */

export interface AdminPayment {
  id: string
  code: string
  plan_id: string
  title: string
  amount: number
  status: string
  created_at: string | null
  submitted_at: string | null
  decided_at: string | null
  reason: string
  email: string
  user_id: string
  decided_by: string
  refund: { at: string | null; by: string } | null
}

export function listPayments(status: string, code = '') {
  const params = new URLSearchParams({ status, code })
  return request<{ items: AdminPayment[]; revenue: Array<{ month: string; amount: number }> }>(
    `/payments?${params}`,
  )
}

export function confirmPayment(id: string, reason: string) {
  return send<unknown>(`/payments/${encodeURIComponent(id)}/confirm`, 'POST', { reason })
}

export function rejectPayment(id: string, reason: string) {
  return send<unknown>(`/payments/${encodeURIComponent(id)}/reject`, 'POST', { reason })
}

export function refundPayment(id: string, reason: string, takeBack: boolean) {
  return send<unknown>(`/payments/${encodeURIComponent(id)}/refund`, 'POST', { reason, take_back: takeBack })
}

/* Video library ------------------------------------------------------------- */

export interface AdminVideo {
  id: string
  topic_id: string
  subject: string
  grade: number
  lang: string
  title: string
  video_url: string
  duration: number | null
  has_audio: boolean | null
  rating_up: number
  rating_down: number
  status: 'cached' | 'public' | 'rejected'
  served: number
  created_at: string | null
}

export interface Topic {
  id: string
  subject: string
  grade: number
  kk: string
  ru: string
}

export function listVideos(status: string, silent: boolean) {
  const params = new URLSearchParams({ status, silent: String(silent) })
  return request<{ items: AdminVideo[]; counts: Record<string, number> }>(`/videos?${params}`)
}

export function listTopics() {
  return request<{ items: Topic[] }>('/topics')
}

export function videoAction(id: string, action: 'publish' | 'reject' | 'delete', reason = '') {
  return send<unknown>(`/videos/${encodeURIComponent(id)}/${action}`, 'POST', { reason })
}

export function editVideo(id: string, changes: { title?: string; topic_id?: string; reason?: string }) {
  return send<AdminVideo>(`/videos/${encodeURIComponent(id)}`, 'PUT', changes)
}

/* Tasks, system, metrics -------------------------------------------------- */

export interface AdminJob {
  id: string
  kind: 'video' | 'assessment' | 'lesson_plan' | 'quiz_draft'
  user_id: string
  email: string
  status: 'queued' | 'running' | 'done' | 'failed'
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  render_sec: number | null
  error_type: string | null
  video: boolean | null
  has_audio: boolean | null
  narration: boolean | null
  duration: number | null
  tts_chars: number | null
  effort: string | null
  summary: string
  restart_of: string | null
  restarted_as: string | null
  restartable: boolean
}

export interface JobCounts {
  queued: number
  running: number
  failed_24h: number
  silent_24h: number
}

export function listJobs(filters: { status: string; kind: string; silent: boolean; page: number }) {
  const params = new URLSearchParams({
    status: filters.status,
    kind: filters.kind,
    silent: String(filters.silent),
    page: String(filters.page),
  })
  return request<{ items: AdminJob[]; total: number; page: number; counts: JobCounts }>(`/jobs?${params}`)
}

export function restartJob(id: string, reason = '') {
  return send<{ ok: boolean; job_id: string }>(`/jobs/${encodeURIComponent(id)}/restart`, 'POST', { reason })
}

export interface SystemState {
  agent: {
    connected: boolean
    connected_at: string | null
    last_seen: string | null
    features: string[]
    heartbeat: { at: string | null; busy: boolean; queue: number | null; held: number | null; uptime_sec: number | null } | null
  }
  queue: { videos: number; documents: number; oldest_sec: number; exports: number }
  jobs: JobCounts
  disk: { free: number | null; total: number | null; free_share: number | null }
  database: { ok: boolean; data_bytes?: number; storage_bytes?: number }
  backend: { uptime_sec: number }
  warnings: string[]
}

export function getSystem() {
  return request<SystemState>('/system')
}

export interface Metrics {
  days: number
  funnel: {
    registered: number
    phone_confirmed: number
    trial_started: number
    trial_used: number
    trial_spent: number
    paid: number
  }
  active_teachers: { day: number; week: number; month: number }
  revenue: Array<{ month: string; amount: number }>
  renders: Array<{ date: string; videos: number; failed: number; silent: number; avg_render_sec: number | null }>
  failures: Array<{ error_type: string; count: number }>
  limit_hits: Array<{
    resource: string
    hits: number
    users: number
    trial_users: number
    ustaz_users: number
    early_users: number
    fair_use_users: number
  }>
  early_period_day: number
  azure: { month: string; chars: number; limit: number; projected: number }
  utc_offset_hours: number
}

export function getMetrics(days: number) {
  return request<Metrics>(`/metrics?days=${days}`)
}

/* Reports from teachers ------------------------------------------------------ */

export interface ProblemReport {
  id: string
  kind: 'explanation' | 'assessment' | 'lesson_plan' | 'quiz' | 'other'
  ref_id: string
  text: string
  page: string
  user_id: string
  email: string
  status: 'open' | 'resolved'
  created_at: string | null
  resolved_at: string | null
  resolved_by: string
}

export function listReports(status: 'open' | 'resolved' | '') {
  return request<{ items: ProblemReport[]; open: number }>(`/reports?status=${status}`)
}

export function resolveReport(id: string, reason = '') {
  return send<{ ok: boolean }>(`/reports/${encodeURIComponent(id)}/resolve`, 'POST', { reason })
}
