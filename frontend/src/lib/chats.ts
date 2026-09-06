/**
 * The history: one chat per question.
 *
 * The backend models a chat as a conversation with many messages, and the old
 * interface used it that way. This one asks a question and gets an
 * explanation, so a chat here holds exactly one exchange - the question and
 * its answer - and the list of chats is the list of past questions. Nothing
 * about the backend prevents follow-ups later; it simply is not what this
 * interface offers.
 */
import type { Answer } from './live'
import type { Conversation, Explanation, Lang, SubjectId } from './types'
import { detectLanguage } from './utils'

export interface ChatSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  video_url?: string | null
  timestamp: string
}

interface ChatDetail extends ChatSummary {
  messages: ChatMessage[]
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) throw new Error(`GET ${path} failed (${response.status})`)
  return (await response.json()) as T
}

export async function listChats(): Promise<ChatSummary[]> {
  const { items } = await get<{ items: ChatSummary[] }>('/chats')
  return items
}

export async function loadChat(chatId: string): Promise<ChatDetail> {
  return get<ChatDetail>(`/chats/${chatId}`)
}

export function toConversation(chat: ChatSummary): Conversation {
  return {
    id: chat.id,
    title: chat.title,
    createdAt: chat.created_at,
    // One chat, one explanation: the chat's own id addresses both.
    explanationId: chat.id,
  }
}

/**
 * Which subject badge to show.
 *
 * The answer comes with one: classify_intent asks the model what subject the
 * question belongs to, and that word is carried out through the socket. It is
 * free text, so it is mapped onto the six the interface knows, and anything
 * unrecognised - or an answer read back from a chat stored before the field
 * existed - falls back to reading the question.
 *
 * The fallback is why this stays a guess rather than becoming a rule: it
 * labels a card. It was defaulting every unmatched question to mathematics,
 * which is how "why does the sky look blue" came back as a maths question.
 */
const SUBJECT_WORDS: Record<string, SubjectId> = {
  math: 'math',
  mathematics: 'math',
  algebra: 'math',
  математика: 'math',
  geometry: 'geometry',
  геометрия: 'geometry',
  physics: 'physics',
  astronomy: 'physics',
  optics: 'physics',
  mechanics: 'physics',
  физика: 'physics',
  астрономия: 'physics',
  chemistry: 'chemistry',
  химия: 'chemistry',
  biology: 'biology',
  биология: 'biology',
  informatics: 'informatics',
  'computer science': 'informatics',
  информатика: 'informatics',
}

/** What the model called it, if the interface has a badge for that. */
export function subjectFromAgent(reported: string): SubjectId | null {
  return SUBJECT_WORDS[reported.trim().toLowerCase()] ?? null
}

const SUBJECT_HINTS: Array<{ subject: SubjectId; words: RegExp }> = [
  { subject: 'physics', words: /физик|күш|жылдамдық|энерги|ток|сила|скорост|инерц/i },
  { subject: 'chemistry', words: /хими|реакция|молекул|қышқыл|кислот|атом/i },
  { subject: 'biology', words: /биолог|жасуша|организм|клетк|растени|өсімдік|фотосинтез/i },
  { subject: 'geometry', words: /геометр|үшбұрыш|бұрыш|аудан|треуголь|угол|площад|пифагор/i },
  { subject: 'informatics', words: /информатик|алгоритм|код|программ/i },
]

export function subjectOf(question: string, reported = ''): SubjectId {
  return (
    subjectFromAgent(reported) ??
    SUBJECT_HINTS.find((entry) => entry.words.test(question))?.subject ??
    'physics'
  )
}

function languageOf(question: string, content: string): Lang {
  // The answer is written in the language of the question, so either tells us
  // - but the answer is longer, and length is what the detector has to work
  // with. The question is the fallback for an answer that never arrived.
  return detectLanguage(content || question)
}

/** What the socket just delivered, as the interface's own shape. */
export function explanationFromAnswer(answer: Answer): Explanation {
  return {
    id: answer.chatId || answer.messageId,
    chatId: answer.chatId,
    question: answer.question,
    subject: subjectOf(answer.question, answer.subject),
    lang: languageOf(answer.question, answer.content),
    createdAt: answer.timestamp,
    markdown: answer.content,
    videoUrl: answer.videoUrl || undefined,
    // An answer with no video is not a failure of the answer: the text is
    // there and worth reading. It is shown as partial, with a retry.
    status: answer.videoUrl ? 'complete' : 'partial',
    saved: false,
    fromCache: answer.fromCache,
    cacheMatch: answer.cacheMatch,
    matchedQuestion: answer.matchedQuestion,
  }
}

/** A stored chat, re-read from the server when its history entry is opened. */
export function explanationFromChat(chat: ChatDetail): Explanation | null {
  const question = chat.messages.find((m) => m.role === 'user')
  const answer = [...chat.messages].reverse().find((m) => m.role === 'assistant')
  if (!answer) return null

  const asked = question?.content || chat.title
  return {
    id: chat.id,
    chatId: chat.id,
    question: asked,
    subject: subjectOf(asked),
    lang: languageOf(asked, answer.content),
    createdAt: answer.timestamp || chat.created_at,
    markdown: answer.content,
    videoUrl: answer.video_url || undefined,
    status: answer.video_url ? 'complete' : 'partial',
    saved: false,
  }
}