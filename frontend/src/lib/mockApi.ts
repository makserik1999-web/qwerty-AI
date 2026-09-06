/**
 * What is left of the stand-in backend: the teacher's assessments.
 *
 * The explanation half is gone - Explain asks the real agent over the socket
 * now, and a mock that returned one of seven canned answers would only be
 * something to reach for by mistake. Generation and grading are still mocked
 * because they have no server yet; that is Ф3 and Ф6.
 */
import { QUESTION_TEMPLATES } from './mockData'
import type {
  Assessment,
  AssessmentQuestion,
  AssessmentType,
  Difficulty,
  Lang,
  SubjectId,
} from './types'
import { sleep, uid } from './utils'

const MARKS: Record<Difficulty, number> = { easy: 2, medium: 3, hard: 4 }

export interface GenerateAssessmentInput {
  subject: SubjectId
  grade: number
  topic: string
  type: AssessmentType
  difficulty: Difficulty
  lang: Lang
  count: number
  shouldFail?: boolean
}

function makeQuestion(
  input: GenerateAssessmentInput,
  index: number,
  offset = 0,
): AssessmentQuestion {
  const templates = QUESTION_TEMPLATES[input.subject][input.lang]
  const template = templates[(index + offset) % templates.length]
  return {
    id: uid('q'),
    text: template.replace('{topic}', input.topic),
    marks: MARKS[input.difficulty] + (index % 2),
  }
}

export async function generateAssessment(
  input: GenerateAssessmentInput,
): Promise<Assessment> {
  await sleep(1800)
  if (input.shouldFail) throw new Error('assessment-failed')
  return {
    id: uid('assess'),
    subject: input.subject,
    grade: input.grade,
    topic: input.topic,
    type: input.type,
    difficulty: input.difficulty,
    lang: input.lang,
    createdAt: new Date().toISOString(),
    questions: Array.from({ length: input.count }, (_, index) =>
      makeQuestion(input, index),
    ),
  }
}

export async function regenerateQuestion(
  input: GenerateAssessmentInput,
  index: number,
): Promise<AssessmentQuestion> {
  await sleep(900)
  return makeQuestion(input, index, Math.floor(Math.random() * 5) + 1)
}

export async function exportDocument(format: 'pdf' | 'docx'): Promise<string> {
  await sleep(1400)
  return `anyq-assessment.${format}`
}
