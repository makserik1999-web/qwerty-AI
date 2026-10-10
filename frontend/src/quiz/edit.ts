/**
 * Editing a quiz: new questions, copies, drafts turned into questions, and
 * the same "what stops this being played" rules the service applies.
 *
 * Ids are made here, in the service's own shape (q-/o- and ten hex digits).
 * The service keeps a well-formed id it is sent, so the card being typed into
 * keeps its identity across saves instead of being renamed by each one.
 */
import type { Lang } from '../lib/types'
import type { ProblemCode, QuizOption, QuizQuestion } from './types'

export function newId(prefix: 'q' | 'o'): string {
  const bytes = new Uint8Array(5)
  crypto.getRandomValues(bytes)
  return `${prefix}-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`
}

function option(text = '', note = ''): QuizOption {
  return { id: newId('o'), text, note }
}

export function blankChoice(): QuizQuestion {
  return {
    id: newId('q'),
    type: 'choice',
    text: '',
    explanation: '',
    topic: '',
    options: [option(), option(), option(), option()],
    correct: '',
  }
}

const TRUE_FALSE: Record<Lang | 'en', [string, string]> = {
  kk: ['Дұрыс', 'Қате'],
  ru: ['Верно', 'Неверно'],
  en: ['True', 'False'],
}

export function blankTrueFalse(lang: Lang | 'en'): QuizQuestion {
  const [yes, no] = TRUE_FALSE[lang] ?? TRUE_FALSE.kk
  return { ...blankChoice(), options: [option(yes), option(no)] }
}

export function blankShort(): QuizQuestion {
  return {
    id: newId('q'),
    type: 'short',
    text: '',
    explanation: '',
    topic: '',
    answer: '',
    unit: '',
    accept: [],
  }
}

/** A copy that shares nothing with the original but its words. */
export function duplicate(question: QuizQuestion): QuizQuestion {
  if (question.type !== 'choice') return { ...question, id: newId('q'), accept: [...(question.accept ?? [])] }
  const options = (question.options ?? []).map((o) => ({ ...o, id: newId('o') }))
  const at = (question.options ?? []).findIndex((o) => o.id === question.correct)
  return { ...question, id: newId('q'), options, correct: at >= 0 ? options[at].id : '' }
}

/** What the agent wrote (options by position), as an editable question. */
export function fromDraft(raw: Record<string, unknown>, keepId?: string): QuizQuestion {
  const text = typeof raw.text === 'string' ? raw.text : ''
  const base = {
    id: keepId ?? newId('q'),
    text,
    explanation: typeof raw.explanation === 'string' ? raw.explanation : '',
    topic: typeof raw.topic === 'string' ? raw.topic : '',
  }
  if (raw.type === 'short') {
    return {
      ...base,
      type: 'short',
      answer: typeof raw.answer === 'string' ? raw.answer : '',
      unit: typeof raw.unit === 'string' ? raw.unit : '',
      accept: Array.isArray(raw.accept) ? raw.accept.filter((a): a is string => typeof a === 'string') : [],
    }
  }
  const options = (Array.isArray(raw.options) ? raw.options : []).map((item) =>
    typeof item === 'string'
      ? option(item)
      : option(
          typeof (item as QuizOption).text === 'string' ? (item as QuizOption).text : '',
          typeof (item as QuizOption).note === 'string' ? (item as QuizOption).note : '',
        ),
  )
  const index = typeof raw.correct === 'number' ? raw.correct : -1
  return { ...base, type: 'choice', options, correct: options[index]?.id ?? '' }
}

function key(text: string): string {
  return text.normalize('NFKC').trim().toLowerCase().replace(/\s+/g, ' ')
}

/** The service's rules (quiz_service/questions.py), for instant feedback. */
export function problemsOf(question: QuizQuestion): ProblemCode[] {
  const found: ProblemCode[] = []
  if (!question.text.trim()) found.push('no_text')
  if (question.type === 'choice') {
    const options = question.options ?? []
    const filled = options.filter((o) => o.text.trim())
    if (options.length < 2) found.push('few_options')
    else if (filled.length < options.length) found.push('empty_option')
    if (!question.correct || !options.some((o) => o.id === question.correct)) found.push('no_correct')
    const keys = filled.map((o) => key(o.text))
    if (new Set(keys).size < keys.length) found.push('duplicate_options')
  } else if (!(question.answer ?? '').trim()) {
    found.push('no_answer')
  }
  return found
}
