/**
 * A stand-in for the backend. Every call is asynchronous and staged so the UI
 * can show the same states it would show against a real service.
 */
import { EXPLANATION_SEEDS, QUESTION_TEMPLATES } from './mockData'
import type {
  Assessment,
  AssessmentQuestion,
  AssessmentType,
  Difficulty,
  Explanation,
  ExplanationBlock,
  Lang,
  SceneId,
  SubjectId,
} from './types'
import { detectLanguage, sleep, uid } from './utils'

export type GenerationStage = 'understand' | 'write' | 'render'
export type Outcome = 'ok' | 'partial' | 'error'

const KEYWORDS: Array<{ scene: SceneId; words: RegExp }> = [
  { scene: 'pythagoras', words: /пифагор|гипотенуз|тік бұрыш|прямоуголь.*треуголь/i },
  { scene: 'quadratic', words: /парабол|квадрат.*(функц|теңдеу|уравн)|дискриминант/i },
  { scene: 'circleArea', words: /дөңгелек|шеңбер|окружност|круг|радиус|π|пи\b/i },
  {
    scene: 'photosynthesis',
    words: /фотосинтез|жапырақ|хлорофилл|лист|растени|өсімдік/i,
  },
  { scene: 'newton', words: /ньютон|күш|үдеу|сила|ускорен|масса|құла|падени/i },
  { scene: 'derivative', words: /туынды|производн|жанама|касательн|предел|шек\b/i },
  { scene: 'reaction', words: /реакция|теңесті|уравня|химич|молекул|валентт/i },
]

const SUBJECT_HINTS: Array<{ subject: SubjectId; words: RegExp }> = [
  { subject: 'physics', words: /физик|күш|жылдамдық|энерги|ток|сила|скорост/i },
  { subject: 'chemistry', words: /хими|реакция|молекул|қышқыл|кислот/i },
  { subject: 'biology', words: /биолог|жасуша|организм|клетк|растени|өсімдік/i },
  { subject: 'geometry', words: /геометр|үшбұрыш|бұрыш|аудан|треуголь|угол|площад/i },
  { subject: 'informatics', words: /информатик|алгоритм|код|программ/i },
]

function pickScene(question: string): SceneId {
  const match = KEYWORDS.find((entry) => entry.words.test(question))
  return match?.scene ?? 'quadratic'
}

function pickSubject(question: string, scene: SceneId): SubjectId {
  const hint = SUBJECT_HINTS.find((entry) => entry.words.test(question))
  return hint?.subject ?? EXPLANATION_SEEDS[scene].subject
}

/**
 * Builds the explanation body. When the question matches a seeded topic we use
 * the seeded copy; otherwise we adapt the seed to the asked question so the
 * prototype always returns something readable.
 */
function buildBlocks(question: string, scene: SceneId, lang: Lang): ExplanationBlock[] {
  const seed = EXPLANATION_SEEDS[scene]
  if (seed.lang === lang) return seed.blocks

  const intro: ExplanationBlock =
    lang === 'kk'
      ? {
          kind: 'paragraph',
          text: `«${question}» деген сұрақты қадамдап қарастырайық. Төменде негізгі идея, шешім барысы және қорытынды берілген.`,
        }
      : {
          kind: 'paragraph',
          text: `Разберём вопрос «${question}» по шагам. Ниже — основная идея, ход рассуждения и вывод.`,
        }

  const body = seed.blocks.filter((block) => block.kind !== 'paragraph')
  const outro: ExplanationBlock =
    lang === 'kk'
      ? {
          kind: 'paragraph',
          text: 'Анимацияда әр қадам ретімен көрсетіледі: алдымен шарт, содан кейін түрлендіру, соңында нәтиже.',
        }
      : {
          kind: 'paragraph',
          text: 'В анимации каждый шаг показан по порядку: сначала условие, затем преобразование, затем результат.',
        }

  return [intro, ...body, outro]
}

export interface GenerateExplanationInput {
  question: string
  lang: Lang | 'auto'
  outcome?: Outcome
  onStage?: (stage: GenerationStage) => void
  /** Shortened in the prototype so the flow stays demonstrable. */
  speed?: number
}

export async function generateExplanation({
  question,
  lang,
  outcome = 'ok',
  onStage,
  speed = 1,
}: GenerateExplanationInput): Promise<Explanation> {
  const resolvedLang: Lang = lang === 'auto' ? detectLanguage(question) : lang
  const scene = pickScene(question)

  onStage?.('understand')
  await sleep(1100 * speed)

  if (outcome === 'error') {
    onStage?.('write')
    await sleep(900 * speed)
    throw new Error('generation-failed')
  }

  onStage?.('write')
  await sleep(1600 * speed)

  onStage?.('render')
  await sleep(2200 * speed)

  const seed = EXPLANATION_SEEDS[scene]
  return {
    id: uid('exp'),
    question: question.trim(),
    subject: pickSubject(question, scene),
    lang: resolvedLang,
    createdAt: new Date().toISOString(),
    scene,
    duration: seed.duration,
    blocks: buildBlocks(question.trim(), scene, resolvedLang),
    status: outcome === 'partial' ? 'partial' : 'complete',
    saved: false,
  }
}

/** Re-runs only the rendering step for an explanation that came back partial. */
export async function renderAnimation(explanation: Explanation): Promise<Explanation> {
  await sleep(2400)
  return { ...explanation, status: 'complete' }
}

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
