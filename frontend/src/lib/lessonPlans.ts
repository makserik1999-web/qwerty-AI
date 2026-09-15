/**
 * Қысқа мерзімді жоспар, from the server.
 *
 * The same contract as assessments and for the same reason: a plan is written
 * once and then edited, so every change is saved. What is on screen and what
 * the teacher submits have to be the same document, and a reload must not
 * quietly hand back a different one.
 */
import { ApiError } from './api'
import type { LessonPlan, LessonPlanDocument } from './types'

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
    throw new ApiError(0, '')
  }

  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      /* nothing useful in the body; the status carries it */
    }
    throw new ApiError(response.status, detail)
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

export async function generateLessonPlan(input: PlanInput): Promise<LessonPlan> {
  return request<LessonPlan>('/lesson-plans', {
    method: 'POST',
    body: JSON.stringify(input),
  })
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
