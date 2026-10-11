/**
 * Қысқа мерзімді жоспар, from the server.
 *
 * The same contract as assessments and for the same reason: a plan is written
 * once and then edited, so every change is saved. What is on screen and what
 * the teacher submits have to be the same document, and a reload must not
 * quietly hand back a different one.
 */
import { ApiError } from './api'
import { BACKGROUND, waitForJob } from './jobs'
import type { LessonPlan, LessonPlanDocument } from './types'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    // `init` first: its own headers are merged below, not left to replace these.
    response = await fetch(`/api${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch {
    throw new ApiError(0, '')
  }

  if (!response.ok) {
    let detail = ''
    let reason = ''
    let data: Record<string, unknown> = {}
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
      // The code is what turns a plan's refusal into the reader's language.
      if (body && typeof body.code === 'string') reason = body.code
      if (body && typeof body === 'object') data = body
    } catch {
      /* nothing useful in the body; the status carries it */
    }
    throw new ApiError(response.status, detail, reason, data)
  }
  return (await response.json()) as T
}

export interface PlanInput {
  subject: string
  grade: number
  topic: string
  lang: string
  duration: number
  section: string
}

/** Written in the background and polled for: a plan can outlast Cloudflare's
 *  100 seconds. An older server answers with the plan itself, which is fine. */
export async function generateLessonPlan(input: PlanInput): Promise<LessonPlan> {
  const answer = await request<LessonPlan | { job_id: string }>('/lesson-plans', {
    method: 'POST',
    body: JSON.stringify(input),
    headers: BACKGROUND,
  })
  if ('job_id' in answer) {
    return waitForJob(answer.job_id, (job) => job.lesson_plan as LessonPlan | undefined)
  }
  return answer
}

export async function listLessonPlans(): Promise<LessonPlan[]> {
  const { items } = await request<{ items: LessonPlan[] }>('/lesson-plans')
  return items
}

export async function loadLessonPlan(id: string): Promise<LessonPlan> {
  return request<LessonPlan>(`/lesson-plans/${id}`)
}

/** The plan as the teacher edited it. Sent whole: the document is what is
 *  submitted, so a partial update would leave the two out of step. */
export async function saveLessonPlan(
  id: string,
  plan: LessonPlanDocument,
): Promise<LessonPlan> {
  return request<LessonPlan>(`/lesson-plans/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ plan }),
  })
}

export async function deleteLessonPlan(id: string): Promise<void> {
  await request<{ deleted: boolean }>(`/lesson-plans/${id}`, { method: 'DELETE' })
}

/** Minutes the stages currently add up to.
 *
 *  Recomputed from what is on screen rather than read from the server's
 *  `minutesPlanned`: the teacher is editing, and a total that still shows the
 *  generated number while the stages say something else is the one number on
 *  this page nobody could trust. */
export function plannedMinutes(plan: LessonPlanDocument): number {
  return (plan.stages || []).reduce((total, stage) => total + (stage.minutes || 0), 0)
}
