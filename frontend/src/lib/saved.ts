/**
 * The Library screen's data, from the server.
 *
 * It used to be a list built in the browser: pressing Save put a card in
 * memory, and the card was gone on the next visit. Nothing reported that -
 * the person found out when they went looking for something they thought they
 * had, which is the worst way to learn it.
 *
 * Saving sends the message id, not the explanation. The text is on screen and
 * could be sent, but then a saved row would be whatever the browser said it
 * was, and the point of saving is that it records what the agent replied.
 */
import { ApiError } from './api'
import type { Explanation, Lang, SubjectId } from './types'

/** One row as the server keeps it. */
interface SavedRow {
  id: string
  question: string
  markdown: string
  videoUrl: string | null
  subject: string
  lang: string
  createdAt: string | null
  savedAt: string | null
  messageId: string
  chatId: string
}

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
      /* the status is all there is */
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

function toExplanation(row: SavedRow): Explanation {
  return {
    id: row.id,
    chatId: row.chatId,
    messageId: row.messageId,
    question: row.question,
    subject: (row.subject || 'physics') as SubjectId,
    lang: (row.lang || 'kk') as Lang,
    createdAt: row.createdAt ?? row.savedAt ?? new Date().toISOString(),
    markdown: row.markdown,
    videoUrl: row.videoUrl ?? undefined,
    // A saved answer whose video has been collected still reads. It is not
    // partial - nothing failed - so it is complete without a file to play.
    status: 'complete',
    saved: true,
  }
}

export async function listSaved(): Promise<Explanation[]> {
  const { items } = await request<{ items: SavedRow[] }>('/library')
  return items.map(toExplanation)
}

export async function saveExplanation(input: {
  messageId: string
  question: string
  subject: string
  lang: string
}): Promise<Explanation> {
  const row = await request<SavedRow>('/library', {
    method: 'POST',
    body: JSON.stringify({
      message_id: input.messageId,
      question: input.question,
      subject: input.subject,
      lang: input.lang,
    }),
  })
  return toExplanation(row)
}

/** The title only. The explanation itself is a record of what was said. */
export async function renameSaved(id: string, question: string): Promise<Explanation> {
  const row = await request<SavedRow>(`/library/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ question }),
  })
  return toExplanation(row)
}

export async function removeSaved(id: string): Promise<void> {
  await request(`/library/${id}`, { method: 'DELETE' })
}
