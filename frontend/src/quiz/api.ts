/**
 * Talking to the quiz service - and, for drafts, to the backend.
 *
 * Teachers are identified by the session cookie, like everywhere else in the
 * app. Students are not signed in at all: the join hands back a token, kept
 * per code in local storage so a refreshed phone rejoins as the same player,
 * and sent as `X-Player-Token`.
 */
import { ApiError } from '../lib/api'
import type {
  AnswerReply,
  CodeLookup,
  DraftInput,
  HostState,
  PlayState,
  Quiz,
  QuizQuestion,
  QuizSettings,
  QuizSummary,
  Results,
} from './types'

/** ApiError plus the service's stable machine word, when it sent one. */
export class QuizError extends ApiError {
  readonly code: string

  constructor(status: number, detail: string, code: string) {
    super(status, detail)
    this.name = 'QuizError'
    this.code = code
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      credentials: 'include',
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch {
    throw new QuizError(0, '', 'network')
  }
  if (!response.ok) {
    let detail = ''
    let code = ''
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
      if (body && typeof body.code === 'string') code = body.code
    } catch {
      /* the status says enough */
    }
    throw new QuizError(response.status, detail, code)
  }
  return (await response.json()) as T
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

/* --------------------------------------------------------------- teacher -- */

export function listQuizzes(): Promise<QuizSummary[]> {
  return call<{ items: QuizSummary[] }>('/api/quiz/quizzes').then((r) => r.items)
}

export interface QuizFields {
  title?: string
  subject?: string
  grade?: number
  lang?: string
  topic?: string
  questions?: Array<Partial<QuizQuestion> & { correct?: string | number }>
  settings?: Partial<QuizSettings>
}

export function createQuiz(fields: QuizFields): Promise<Quiz> {
  return call<Quiz>('/api/quiz/quizzes', json('POST', fields))
}

export function loadQuiz(id: string): Promise<Quiz> {
  return call<Quiz>(`/api/quiz/quizzes/${id}`)
}

export function saveQuiz(id: string, fields: QuizFields): Promise<Quiz> {
  return call<Quiz>(`/api/quiz/quizzes/${id}`, json('PUT', fields))
}

export function copyQuiz(id: string): Promise<Quiz> {
  return call<Quiz>(`/api/quiz/quizzes/${id}/copy`, json('POST'))
}

export function deleteQuiz(id: string): Promise<void> {
  return call(`/api/quiz/quizzes/${id}`, json('DELETE'))
}

/** Questions written by the agent, through the backend. Not saved anywhere. */
export function draftQuestions(input: DraftInput): Promise<QuizFields['questions']> {
  return call<{ questions: QuizFields['questions'] }>('/api/quiz-drafts', json('POST', input)).then(
    (r) => r.questions,
  )
}

export function openRun(
  quizId: string,
  settings: QuizSettings,
  classLabel: string,
): Promise<HostState> {
  return call<HostState>(`/api/quiz/quizzes/${quizId}/sessions`, json('POST', { settings, classLabel }))
}

export function loadRun(sessionId: string): Promise<HostState> {
  return call<HostState>(`/api/quiz/sessions/${sessionId}`)
}

export function startRun(sessionId: string): Promise<HostState> {
  return call<HostState>(`/api/quiz/sessions/${sessionId}/start`, json('POST'))
}

export function endRun(sessionId: string): Promise<HostState> {
  return call<HostState>(`/api/quiz/sessions/${sessionId}/end`, json('POST'))
}

export function removePlayer(sessionId: string, playerId: string): Promise<void> {
  return call(`/api/quiz/sessions/${sessionId}/players/${playerId}`, json('DELETE'))
}

export function loadResults(sessionId: string): Promise<Results> {
  return call<Results>(`/api/quiz/sessions/${sessionId}/results`)
}

export function deleteRun(sessionId: string): Promise<void> {
  return call(`/api/quiz/sessions/${sessionId}`, json('DELETE'))
}

/* --------------------------------------------------------------- student -- */

const TOKEN_KEY = 'anyq.quiz.player.'

export function savedToken(code: string): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY + code)
  } catch {
    return null
  }
}

export function keepToken(code: string, token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY + code, token)
    else localStorage.removeItem(TOKEN_KEY + code)
  } catch {
    /* a private window: the phone simply cannot rejoin after a refresh */
  }
}

export function lookupCode(code: string): Promise<CodeLookup> {
  return call<CodeLookup>(`/api/play/code/${encodeURIComponent(code)}`, {
    credentials: 'omit',
  })
}

export function joinRun(code: string, name: string): Promise<{ token: string; state: PlayState }> {
  return call(`/api/play/code/${encodeURIComponent(code)}/join`, {
    ...json('POST', { name }),
    credentials: 'omit',
  })
}

function player(token: string): RequestInit {
  return { credentials: 'omit', headers: { 'X-Player-Token': token } }
}

export function playState(token: string): Promise<PlayState> {
  return call<PlayState>('/api/play/state', player(token))
}

export function sendAnswer(
  token: string,
  body: { questionId: string; optionId?: string; text?: string; skip?: boolean },
): Promise<AnswerReply> {
  return call<AnswerReply>('/api/play/answer', {
    ...player(token),
    ...json('POST', body),
    headers: { 'X-Player-Token': token },
  })
}

export function socketUrl(path: string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}${path}`
}
