export type Role = 'student' | 'teacher'

/**
 * Content language. Explanations and assessments are produced in Kazakh or
 * Russian; `auto` is only valid as a request option.
 */
export type Lang = 'kk' | 'ru'
export type LangChoice = Lang | 'auto'

/** Interface language. English is available for the UI only, not for content. */
export type UiLang = Lang | 'en'

export type SubjectId =
  'math' | 'geometry' | 'physics' | 'chemistry' | 'biology' | 'informatics'

export type SceneId =
  | 'pythagoras'
  | 'quadratic'
  | 'circleArea'
  | 'photosynthesis'
  | 'newton'
  | 'derivative'
  | 'reaction'

/** A block of generated explanation text. Formulas are set apart from prose. */
export type ExplanationBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'formula'; text: string }
  | { kind: 'step'; title: string; text: string }

export type ExplanationStatus = 'complete' | 'partial'

export interface Explanation {
  id: string
  question: string
  subject: SubjectId
  lang: Lang
  createdAt: string
  status: ExplanationStatus
  saved: boolean

  /* A real answer has `markdown` and `videoUrl`: the model writes prose with
     formulas in it, and Manim renders an mp4 for that specific question.
     `blocks`, `scene` and `duration` belong to the seeded library data, which
     was authored before there was a server to ask - the landing page still
     plays those scenes, and the library switches over in Ф5. Exactly one of
     the two shapes is filled in for any given explanation. */

  /** Markdown as the model wrote it, with LaTeX for the formulas. */
  markdown?: string
  /** Served from /media, behind the session cookie. */
  videoUrl?: string

  blocks?: ExplanationBlock[]
  scene?: SceneId
  /** Seconds — the length of a built-in scene. */
  duration?: number

  /** Served from the answer library instead of being generated just now. */
  fromCache?: boolean
  /** "exact" or "semantic". A semantic hit answered a DIFFERENT wording. */
  cacheMatch?: string
  /** The stored question a semantic hit was matched against. */
  matchedQuestion?: string
  /** The chat it was filed under, so the history can open it again. */
  chatId?: string
  /** The message that carried it. Saving is addressed by this, not by a copy. */
  messageId?: string
}

export interface Conversation {
  id: string
  title: string
  createdAt: string
  explanationId: string
}

export type AssessmentType = 'sor' | 'soch' | 'quiz'
export type Difficulty = 'easy' | 'medium' | 'hard'

export interface AssessmentQuestion {
  id: string
  text: string
  marks: number
  hint?: string
}

export interface Assessment {
  id: string
  subject: SubjectId
  grade: number
  topic: string
  type: AssessmentType
  difficulty: Difficulty
  lang: Lang
  questions: AssessmentQuestion[]
  createdAt: string
}

export type UploadStatus = 'queued' | 'uploading' | 'processing' | 'done' | 'failed'

export interface UploadFile {
  id: string
  name: string
  sizeKb: number
  status: UploadStatus
  progress: number
  error?: string
}

export interface GradedQuestion {
  number: number
  awarded: number
  max: number
  note: string
}

export interface Submission {
  id: string
  student: string
  fileName: string
  score: number
  max: number
  gradedAt: string
  status: 'graded' | 'overridden' | 'failed'
  breakdown: GradedQuestion[]
}

export type TransactionAction = 'explanation' | 'assessment' | 'grading' | 'topup'

export interface Transaction {
  id: string
  date: string
  action: TransactionAction
  detail: string
  quantity: number
  /** Negative for spending, positive for a top-up. In tenge. */
  amount: number
}

export interface User {
  id: string
  /** Derived from the email at signup; the account's stable handle. */
  username: string
  name: string
  email: string
  role: Role
}
