/**
 * The real backend, in place of `mockApi`'s account handling.
 *
 * Identity lives in an HttpOnly session cookie the browser sends on its own,
 * so nothing here passes a user id or a token: every request is `credentials:
 * 'include'` and the server works out who is asking. That also means a signed
 * -in person is signed in in every tab, and signing out ends all of them.
 *
 * Errors come back as an `ApiError` carrying the status, because the caller
 * usually wants to say something different for "wrong password" than for
 * "that address is taken" - and it should say it in the reader's language,
 * which the server does not know. `detail` is kept for the cases nothing has
 * been translated for yet.
 */
import { deviceId, inviteRef } from './device'
import type { StringKey } from './strings'
import type { Role, StaffRole } from './types'

/** What /api/auth/* returns. `username` is derived server-side from the email. */
export interface ApiUser {
  id: string
  username: string
  email: string | null
  name: string
  role: Role
  /** Present only for staff. */
  staff_role?: StaffRole
  created_at: string | null
  email_verified: boolean
  /** 77071234567, or null. */
  phone: string | null
  phone_verified: boolean
  /** False for an account made with Google that never set a password. */
  has_password: boolean
  /** Has not agreed to the current privacy policy yet. */
  consent_needed?: boolean
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  /** The server's machine-readable reason, when it gave one. */
  readonly reason: string
  /** Anything else in the error body: retry_after, attempts_left. */
  readonly data: Record<string, unknown>

  constructor(status: number, detail: string, reason = '', data: Record<string, unknown> = {}) {
    super(detail || `Request failed (${status})`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.reason = reason
    this.data = data
  }
}

const PLAN_RESOURCES = ['videos', 'assessments', 'quiz_drafts', 'lesson_plans']

/**
 * The string for a refusal any generating request can come back with - an
 * unconfirmed email, no plan, a plan used up - or null for anything else.
 * Takes the code and resource directly too, for the video socket's frames.
 */
export function refusalKey(code: string, resource?: unknown): StringKey | null {
  if (code === 'email_unverified') return 'auth.verifyFirst'
  if (code === 'plan_required') return 'plan.refusal.required'
  if (code === 'plan_exhausted') {
    const kind = PLAN_RESOURCES.includes(String(resource)) ? String(resource) : 'videos'
    return `plan.refusal.exhausted.${kind}` as StringKey
  }
  return null
}

export function generationRefusal(error: unknown): StringKey | null {
  if (!(error instanceof ApiError)) return null
  const code = error.reason || (error as { code?: string }).code || ''
  return refusalKey(code, error.data.resource)
}

/** Status 0 means the request never arrived - offline, or the server is down. */
export const NETWORK_ERROR = 0

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
      ...init,
    })
  } catch {
    throw new ApiError(NETWORK_ERROR, '')
  }

  if (!response.ok) {
    let detail = ''
    let reason = ''
    let data: Record<string, unknown> = {}
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
      if (body && typeof body.code === 'string') reason = body.code
      if (body && typeof body === 'object') data = body
    } catch {
      /* a non-JSON error body tells us nothing useful; the status carries it */
    }
    throw new ApiError(response.status, detail, reason, data)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export interface SignUpInput {
  name: string
  email: string
  password: string
  role: Role
  /** The privacy box was ticked. */
  consent: boolean
}

export async function signUp(input: SignUpInput): Promise<ApiUser> {
  // The invite code a colleague's link brought, and this browser's id - both
  // for the referral, and the second for spotting many accounts in one place.
  const { user } = await request<{ user: ApiUser }>('/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ ...input, ref: inviteRef() || undefined, device: deviceId() || undefined }),
  })
  return user
}

export async function signIn(input: { email: string; password: string }): Promise<ApiUser> {
  const { user } = await request<{ user: ApiUser }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ ...input, device: deviceId() || undefined }),
  })
  return user
}

export async function signOut(): Promise<void> {
  await request('/auth/logout', { method: 'POST' })
}

/**
 * Who the cookie belongs to, or null when it belongs to nobody.
 *
 * A missing session is the ordinary state for a first visit, so 401 is not
 * treated as a failure here. Anything else is - a server that is down must
 * not look the same as a signed-out visitor, or a blip would sign everyone
 * out and lose whatever they were in the middle of.
 */
/** Agree to the current privacy policy. */
export async function giveConsent(): Promise<ApiUser> {
  const { user } = await request<{ user: ApiUser }>('/auth/consent', { method: 'POST' })
  return user
}

export async function currentUser(): Promise<ApiUser | null> {
  try {
    const { user } = await request<{ user: ApiUser }>('/auth/me')
    return user
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

export async function updateProfile(input: {
  name?: string
  email?: string
}): Promise<ApiUser> {
  const { user } = await request<{ user: ApiUser }>('/auth/profile', {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  return user
}

export async function deleteAccount(): Promise<void> {
  await request('/auth/account', { method: 'DELETE' })
}

/** What is left of the generation budget - the real limits, from the server. */
export interface Quota {
  used_hour: number
  used_day: number
  limit_hour: number
  limit_day: number
  remaining_hour: number
  remaining_day: number
}

export async function getQuota(): Promise<Quota> {
  return request<Quota>('/quota')
}

/** Which sign-in and confirmation methods the server has set up. */
export async function getProviders(): Promise<{ google: boolean; phone: boolean }> {
  return request('/auth/providers')
}

/** Where the "Continue with Google" button sends the browser. */
export function googleStartUrl(role?: Role, consent = false): string {
  const params = new URLSearchParams()
  if (role) params.set('role', role)
  // Ticked on the sign-up form; a new account made without it is asked inside.
  if (consent) params.set('consent', '1')
  const ref = inviteRef()
  if (ref) params.set('ref', ref)
  const device = deviceId()
  if (device) params.set('device', device)
  const query = params.toString()
  return query ? `/api/auth/google/start?${query}` : '/api/auth/google/start'
}

/* Referrals ----------------------------------------------------------------- */

export interface ReferralSummary {
  code: string
  link: string
  invited: number
  paid: number
  months_this_year: number
  cap: number
  invitee_bonus_videos: number
}

export async function getReferrals(): Promise<ReferralSummary> {
  return request('/referrals')
}

export async function resendVerification(): Promise<{ ok: boolean; already?: boolean }> {
  return request('/auth/email/resend', { method: 'POST' })
}

export async function verifyEmail(token: string): Promise<{ ok: boolean; email: string }> {
  return request('/auth/email/verify', { method: 'POST', body: JSON.stringify({ token }) })
}

export async function forgotPassword(email: string): Promise<void> {
  await request('/auth/password/forgot', { method: 'POST', body: JSON.stringify({ email }) })
}

export async function resetPassword(token: string, password: string): Promise<ApiUser> {
  const { user } = await request<{ user: ApiUser }>('/auth/password/reset', {
    method: 'POST',
    body: JSON.stringify({ token, password }),
  })
  return user
}

export async function startPhone(
  phone: string,
): Promise<{ ok: boolean; already?: boolean; phone?: string; retry_after?: number }> {
  return request('/auth/phone/start', { method: 'POST', body: JSON.stringify({ phone }) })
}

export async function verifyPhone(phone: string, code: string): Promise<ApiUser> {
  const { user } = await request<{ user: ApiUser }>('/auth/phone/verify', {
    method: 'POST',
    body: JSON.stringify({ phone, code }),
  })
  return user
}

/* Plans ------------------------------------------------------------------- */

export type PlanResource = 'videos' | 'assessments' | 'quiz_drafts' | 'lesson_plans'
type PerResource<T> = Record<PlanResource, T>

export interface PlanSummary {
  kind: 'free' | 'trial' | 'ustaz'
  plan_id: string | null
  title: string | null
  limits: Partial<PerResource<number | null>>
  used: PerResource<number>
  /** null = unlimited */
  available: PerResource<number | null>
  carryover: number
  extra_videos: number
  watermark: boolean
  max_effort: 'low' | 'medium' | 'high' | null
  docx_signature: boolean
  /** Why a free account has no trial: teacher_only, phone_required, phone_used. */
  trial_unavailable: string | null
  trial_used_up: boolean
  subscription: null | {
    plan_id: string
    title: string | null
    status: 'active' | 'paused' | 'expired'
    expires_at: string | null
    period_end: string | null
    pause_until: string | null
    can_pause: boolean
    suggest_year: boolean
  }
}

export interface PlanOffer {
  _id: string
  kind: 'subscription' | 'addon'
  title: string
  price: number
  period?: 'month' | 'school_year'
  limits?: Partial<PerResource<number | null>>
  videos?: number
}

export async function getPlan(): Promise<{
  plan: PlanSummary
  offers: PlanOffer[]
  trial_limits: Partial<PerResource<number | null>> | null
}> {
  return request('/plan')
}

export async function pausePlan(): Promise<{ plan: PlanSummary }> {
  return request('/plan/pause', { method: 'POST' })
}

export async function resumePlan(): Promise<{ plan: PlanSummary }> {
  return request('/plan/resume', { method: 'POST' })
}

/** Where the Word file of a paper downloads from. */
export function assessmentDocxUrl(id: string): string {
  return `/api/assessments/${encodeURIComponent(id)}/docx`
}

/* Payments ------------------------------------------------------------------ */

export interface Payment {
  id: string
  code: string
  plan_id: string
  title: string
  amount: number
  status: 'awaiting' | 'submitted' | 'confirmed' | 'rejected' | 'refunded' | 'expired' | 'cancelled'
  created_at: string | null
  submitted_at: string | null
  decided_at: string | null
  reason: string
}

export interface KaspiDetails {
  phone: string
  name: string
  link: string
  note: string
}

export async function getPayments(): Promise<{
  enabled: boolean
  details: KaspiDetails | null
  items: Payment[]
}> {
  return request('/payments')
}

export async function orderPlan(planId: string): Promise<Payment> {
  return request('/payments', { method: 'POST', body: JSON.stringify({ plan_id: planId }) })
}

export async function reportPaid(id: string): Promise<Payment> {
  return request(`/payments/${encodeURIComponent(id)}/submitted`, { method: 'POST' })
}

export async function cancelOrder(id: string): Promise<Payment> {
  return request(`/payments/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}

/* Topic videos ------------------------------------------------------------- */

export interface Rating {
  up: number
  down: number
  mine: number
}

export async function rateVideo(id: string, value: 'up' | 'down' | 'none'): Promise<Rating> {
  return request(`/videos/${encodeURIComponent(id)}/rate`, {
    method: 'POST',
    body: JSON.stringify({ value }),
  })
}

export interface ShowcaseVideo {
  id: string
  topic_id: string
  subject: string
  grade: number
  lang: string
  title: string
  video_url: string
  text: string
  duration: number | null
  has_audio: boolean | null
  rating_up: number
  rating_down: number
}

export async function getShowcase(subject = '', grade = 0): Promise<{ items: ShowcaseVideo[] }> {
  const params = new URLSearchParams()
  if (subject) params.set('subject', subject)
  if (grade) params.set('grade', String(grade))
  return request(`/showcase?${params}`)
}
