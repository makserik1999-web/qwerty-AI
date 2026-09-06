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
  scene: SceneId
  /** Seconds — the length of the rendered animation. */
  duration: number
  blocks: ExplanationBlock[]
  status: ExplanationStatus
  saved: boolean
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
  name: string
  email: string
  role: Role
}
