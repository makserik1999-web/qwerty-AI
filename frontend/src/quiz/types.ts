/**
 * The quiz service's contract, as the interface reads it.
 *
 * Kept beside the quiz screens rather than in lib/types.ts: the quiz service
 * is a service of its own, and its screens are a module of their own - the
 * day either is split out, this file goes with them.
 */
import type { Lang, SubjectId } from '../lib/types'

export type QuestionKind = 'choice' | 'short'

export interface QuizOption {
  id: string
  text: string
  /** Why a student would pick this wrong option. Never sent to a student. */
  note: string
}

export interface QuizQuestion {
  id: string
  type: QuestionKind
  text: string
  explanation: string
  topic: string
  /** choice */
  options?: QuizOption[]
  correct?: string
  /** short */
  answer?: string
  unit?: string
  accept?: string[]
}

export interface QuizSettings {
  /** Minutes; 0 means the teacher ends it. */
  timeLimitMin: number
  shuffleQuestions: boolean
  shuffleOptions: boolean
  showResults: boolean
  leaderboard: boolean
  lateJoin: boolean
}

export type ProblemCode =
  | 'no_text'
  | 'few_options'
  | 'empty_option'
  | 'no_correct'
  | 'duplicate_options'
  | 'no_answer'

export type RunStatus = 'lobby' | 'running' | 'ended'

export interface RunSummary {
  id: string
  code: string
  status: RunStatus
  classLabel: string
  createdAt: string
  startsAt: string | null
  endedAt: string | null
  players: number
  averagePercent: number | null
}

export interface Quiz {
  id: string
  title: string
  subject: SubjectId | 'other'
  grade: number
  lang: Lang | 'en'
  topic: string
  questions: QuizQuestion[]
  settings: QuizSettings
  /** Only questions with something wrong appear. Empty means playable. */
  problems: Record<string, ProblemCode[]>
  questionCount: number
  createdAt: string
  updatedAt: string
  runs?: RunSummary[]
}

export interface QuizSummary {
  id: string
  title: string
  subject: SubjectId | 'other'
  grade: number
  lang: Lang | 'en'
  questionCount: number
  kinds: { choice: number; short: number }
  ready: boolean
  createdAt: string
  updatedAt: string
  lastRun: RunSummary | null
}

/* ----------------------------------------------------------- the board -- */

export type PlayerStatus = 'lobby' | 'countdown' | 'playing' | 'finished' | 'kicked'

export interface HostPlayer {
  id: string
  name: string
  status: PlayerStatus
  joinedAt: string
  answered: number
  correct: number
  score: number
  streak: number
  total: number
}

export interface QuestionTally {
  id: string
  index: number
  type: QuestionKind
  text: string
  answered: number
  correct: number
  options?: Array<{ id: string; text: string; count: number; correct: boolean }>
}

export interface HostState {
  id: string
  quizId: string
  title: string
  code: string
  status: RunStatus
  classLabel: string
  settings: QuizSettings
  questionCount: number
  createdAt: string
  startsAt: string | null
  endedAt: string | null
  serverNow: string
  players: HostPlayer[]
  leaders: string[]
  questions: QuestionTally[]
}

export type HostEvent =
  | { type: 'snapshot'; state: HostState }
  | { type: 'joined'; player: HostPlayer }
  | { type: 'left'; playerId: string }
  | {
      type: 'answer'
      player: HostPlayer
      questionId: string
      optionId: string | null
      correct: boolean
    }
  | { type: 'finished'; player: HostPlayer }
  | {
      type: 'status'
      status: RunStatus
      startsAt: string | null
      endedAt?: string | null
      serverNow: string
    }
  | { type: 'pong' }

/* --------------------------------------------------------- the phone -- */

export interface PlayQuestion {
  id: string
  type: QuestionKind
  text: string
  index: number
  total: number
  options?: Array<{ id: string; text: string }>
  unit?: string
}

export interface PlayResult {
  answered: number
  total: number
  /** The session is still open: others are finishing. */
  waiting: boolean
  /* Only when the teacher shows results. */
  score?: number
  correct?: number
  bestStreak?: number
  answers?: Array<{ questionId: string; correct: boolean | null }>
  rank?: number
  of?: number
}

export interface PlayState {
  status: PlayerStatus
  sessionStatus: RunStatus
  title: string
  questionCount: number
  showResults: boolean
  leaderboard: boolean
  serverNow: string
  startsAt: string | null
  deadline: string | null
  player: { id: string; name: string }
  progress: { answered: number; total: number; score: number; correct: number; streak: number }
  question: PlayQuestion | null
  result: PlayResult | null
}

export interface Reveal {
  explanation: string
  correctOptionId?: string
  answer?: string
}

export interface AnswerReply {
  correct: boolean | null
  points: number | null
  reveal: Reveal | null
  state: PlayState
}

export interface CodeLookup {
  code: string
  title: string
  status: RunStatus
  questionCount: number
  timeLimitMin: number
  players: number
  joinable: boolean
}

export type PlayEvent =
  | { type: 'state'; state: PlayState; players: number }
  | { type: 'status'; status: RunStatus; startsAt: string | null; serverNow: string }
  | { type: 'lobby'; players: number }
  | { type: 'kicked' }
  | { type: 'refresh' }
  | { type: 'pong' }

/* ------------------------------------------------------------ results -- */

export interface ResultQuestion {
  id: string
  index: number
  type: QuestionKind
  text: string
  explanation: string
  topic: string
  answered: number
  correct: number
  rate: number | null
  skipped: number
  medianMs: number | null
  options?: Array<{ id: string; text: string; note: string; correct: boolean; count: number }>
  answer?: string
  unit?: string
  accept?: string[]
  wrongAnswers?: Array<{ text: string; count: number }>
}

export interface ResultPlayer {
  id: string
  name: string
  rank: number
  score: number
  correct: number
  answered: number
  total: number
  percent: number
  durationSec: number | null
  finished: boolean
  bestStreak: number
  answers: Array<{ questionId: string; correct: boolean | null; value: string; skipped: boolean }>
}

export interface Insight {
  questionId: string
  questionIndex: number
  questionText: string
  answer: string
  note: string
  count: number
  share: number
}

export interface Results {
  session: {
    id: string
    quizId: string
    title: string
    code: string
    status: RunStatus
    classLabel: string
    subject: SubjectId | 'other'
    grade: number
    lang: Lang | 'en'
    settings: QuizSettings
    createdAt: string
    startsAt: string | null
    endedAt: string | null
  }
  summary: {
    players: number
    finished: number
    questionCount: number
    averagePercent: number | null
    medianDurationSec: number | null
    hardest: string | null
    easiest: string | null
  }
  questions: ResultQuestion[]
  players: ResultPlayer[]
  insights: Insight[]
}

export interface DraftInput {
  subject: SubjectId
  grade: number
  topic: string
  lang: Lang
  count: number
  mix: 'choice' | 'mixed' | 'short'
  difficulty: 'easy' | 'medium' | 'hard'
  avoid?: string[]
}
