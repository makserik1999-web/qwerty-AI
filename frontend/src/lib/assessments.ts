/**
 * Assessment papers, from the server.
 *
 * Replaces the mocked half of mockApi for Generate. A paper is written once
 * and then edited, so every change is saved: the questions on screen and the
 * questions that get printed have to be the same paper, and a reload must not
 * quietly hand back a different one.
 */
import { ApiError } from './api'
import type { Assessment, AssessmentQuestion } from './types'

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

export interface GenerateInput {
  subject: string
  grade: number
  topic: string
  type: string
  difficulty: string
  lang: string
  count: number
}

export async function generateAssessment(input: GenerateInput): Promise<Assessment> {
  return request<Assessment>('/assessments', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function listAssessments(): Promise<Assessment[]> {
  const { items } = await request<{ items: Assessment[] }>('/assessments')
  return items
}

export async function loadAssessment(id: string): Promise<Assessment> {
  return request<Assessment>(`/assessments/${id}`)
}

/**
 * The paper as edited, in one write.
 *
 * The whole list goes rather than a patch per question: a paper is a document,
 * and a sequence of per-question saves can interleave into something that was
 * never on anybody's screen.
 */
export async function saveQuestions(
  id: string,
  questions: AssessmentQuestion[],
): Promise<Assessment> {
  return request<Assessment>(`/assessments/${id}/questions`, {
    method: 'PUT',
    body: JSON.stringify({
      questions: questions.map((q) => ({ id: q.id, text: q.text, marks: q.marks })),
    }),
  })
}

/** Swap one question. Returns the whole paper, because that is what changed. */
export async function regenerateQuestion(
  id: string,
  questionId: string,
): Promise<Assessment> {
  return request<Assessment>(`/assessments/${id}/questions/${questionId}/regenerate`, {
    method: 'POST',
  })
}

export async function deleteAssessment(id: string): Promise<void> {
  await request(`/assessments/${id}`, { method: 'DELETE' })
}
