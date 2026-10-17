import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { useWebSocket } from './useWebSocket'

/**
 * The socket, and the one question at a time going through it.
 *
 * Asking is three frames, not one: a chat has to exist before a question can
 * be filed under it, so `ask` sends `create_chat`, waits for `chat_created`,
 * then sends `user_message` and waits for `ai_response`. All of that is folded
 * into a single promise here, because no screen benefits from knowing about
 * the middle step.
 *
 * Only one question can be in flight. The composer disables itself while a
 * video is being made, so a second one is not reachable through the interface
 * - and the socket gives us nothing to correlate two `chat_created` frames
 * with, so guessing which answer belongs to which question would be exactly
 * the kind of mix-up that is invisible until someone gets the wrong video.
 */

export type AskStage = 'understand' | 'write' | 'render'

/**
 * How long to wait for an answer before giving up on hearing about it.
 *
 * Generous on purpose: the slowest render measured was 154 seconds, and a
 * question cut off while it was still being rendered would be the worse
 * mistake. But not unbounded - a promise that never settles is a spinner that
 * runs until the tab is closed, which is what a person sees when an answer is
 * lost somewhere between the agent and this page. That happened, and the
 * screen said nothing at all for five minutes after the video was ready.
 *
 * The render is not cancelled by this. It finishes, it is saved to the chat
 * and written to the cache - which is why the message says to look in the
 * history rather than implying the work was thrown away.
 */
const ANSWER_DEADLINE_MS: Record<Effort, number> = {
  low: 5 * 60 * 1000,
  medium: 5 * 60 * 1000,
  high: 10 * 60 * 1000,
}

/**
 * Why "high" gets twice as long.
 *
 * Five minutes was set when everything rendered at 480p15. At 1080p60 the
 * same animation takes about six times as long to render - measured, 11.4
 * seconds against 68.8 on one 37-second scene - and "high" also allows three
 * repair attempts, each of which renders again. A long video that needed two
 * repairs would pass five minutes while working perfectly.
 *
 * The deadline exists to stop a spinner over a LOST answer, not over a slow
 * one. Timing out a render that is still going produces exactly the wrong
 * message: it tells somebody their answer went missing while it is being
 * made.
 */

/** Ran out of patience, not out of luck: the answer may still be coming. */
export class AnswerTimeout extends Error {
  constructor() {
    super('answer timed out')
    this.name = 'AnswerTimeout'
  }
}

/** What the agent produced, before the interface makes an Explanation of it. */
export interface Answer {
  chatId: string
  messageId: string
  question: string
  /** Markdown, as written by the model. */
  content: string
  videoUrl: string
  /** The subject the model decided on, free text - '' from an older agent. */
  subject: string
  timestamp: string
  fromCache: boolean
  cacheTier: string
  /** "exact" or "semantic"; a semantic hit answered a DIFFERENT wording. */
  cacheMatch: string
  matchedQuestion: string
  /** The topic video this answer is, if it was filed or served by topic. */
  videoCacheId: string
  rating: { up: number; down: number; mine: number } | null
}

/** How long the video should run. The seconds are approximate on purpose -
 *  see VideoLengthPicker. */
export type VideoLength = 'short' | 'medium' | 'long'

/** How much is spent making the video. Picture quality is the visible part. */
export type Effort = 'low' | 'medium' | 'high'

/** Which way up the video is: 16:9 for a screen, 9:16 for a phone. */
export type Orientation = 'landscape' | 'portrait'

export interface AskInput {
  question: string
  narration: boolean
  narrationVoice: string
  videoLength: VideoLength
  effort: Effort
  /** Skip every library answer and make a new video for this question. */
  forceRegenerate?: boolean
  /** The answer language; absent means the language of the question. */
  outputLanguage?: 'kk' | 'ru' | 'en'
  /** Absent means landscape, as every video was before the choice. */
  orientation?: Orientation
}

interface LiveValue {
  isConnected: boolean
  /** Which of the three stages the agent says it is on, while one is running. */
  stage: AskStage | null
  ask: (input: AskInput) => Promise<Answer>
}

const LiveContext = createContext<LiveValue | null>(null)

interface Pending {
  question: string
  chatId: string | null
  resolve: (answer: Answer) => void
  reject: (error: Error) => void
  timer: ReturnType<typeof setTimeout>
}

/** Failed because the server said so, rather than because the wire broke. */
export class AgentError extends Error {
  /** A machine-readable reason, when the server gave one (e.g. teacher_only). */
  readonly code: string

  constructor(message: string, code = '') {
    super(message)
    this.name = 'AgentError'
    this.code = code
  }
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function readRating(value: unknown): Answer['rating'] {
  if (!value || typeof value !== 'object') return null
  const r = value as Record<string, unknown>
  return { up: Number(r.up) || 0, down: Number(r.down) || 0, mine: Number(r.mine) || 0 }
}

export function LiveProvider({
  enabled,
  children,
}: {
  enabled: boolean
  children: React.ReactNode
}) {
  const [stage, setStage] = useState<AskStage | null>(null)
  const pendingRef = useRef<Pending | null>(null)
  const sendRef = useRef<((type: string, data: Record<string, unknown>) => boolean) | null>(
    null,
  )
  const inputRef = useRef<AskInput | null>(null)

  const settle = useCallback((run: (pending: Pending) => void) => {
    const pending = pendingRef.current
    if (!pending) return
    clearTimeout(pending.timer)
    pendingRef.current = null
    inputRef.current = null
    setStage(null)
    run(pending)
  }, [])

  const onMessage = useCallback(
    (frame: Record<string, unknown>) => {
      const type = str(frame.type)
      const data = (frame.data ?? {}) as Record<string, unknown>
      const pending = pendingRef.current

      if (type === 'chat_created') {
        if (!pending || pending.chatId) return
        const chatId = str(data.id)
        pending.chatId = chatId
        const input = inputRef.current
        sendRef.current?.('user_message', {
          chat_id: chatId,
          prompt: pending.question,
          screenshots: [],
          narration: input?.narration ?? true,
          narration_voice: input?.narrationVoice ?? 'aigul',
          video_length: input?.videoLength ?? 'medium',
          effort: input?.effort ?? 'medium',
          ...(input?.outputLanguage ? { output_language: input.outputLanguage } : {}),
          ...(input?.orientation === 'portrait' ? { orientation: 'portrait' } : {}),
          ...(input?.forceRegenerate ? { force_regenerate: true } : {}),
        })
        return
      }

      if (type === 'message_received') {
        // The question is on the agent's queue. Nothing more is said until the
        // answer, unless the agent reports its stages.
        setStage((current) => current ?? 'understand')
        return
      }

      if (type === 'progress') {
        const next = str(data.stage)
        if (next === 'understand' || next === 'write' || next === 'render') {
          setStage(next)
        }
        return
      }

      if (type === 'ai_response') {
        if (!pending) return
        const chatId = str(data.chat_id)
        if (pending.chatId && chatId && chatId !== pending.chatId) return
        settle((p) =>
          p.resolve({
            chatId: chatId || (p.chatId ?? ''),
            messageId: str(data.message_id),
            question: p.question,
            content: str(data.content),
            videoUrl: str(data.video_url),
            subject: str(data.subject),
            timestamp: str(data.timestamp) || new Date().toISOString(),
            fromCache: data.from_cache === true,
            cacheTier: str(data.cache_tier),
            cacheMatch: str(data.cache_match),
            matchedQuestion: str(data.matched_question),
            videoCacheId: str(data.video_cache_id),
            rating: readRating(data.rating),
          }),
        )
        return
      }

      if (type === 'error') {
        if (!pending) return
        const chatId = str(data.chat_id)
        if (pending.chatId && chatId && chatId !== pending.chatId) return
        settle((p) => p.reject(new AgentError(str(data.message) || 'agent error', str(data.code))))
      }
    },
    [settle],
  )

  const onDisconnect = useCallback(() => {
    // A dropped socket is not an answer that never comes: the request may well
    // have been rendered. But this session cannot hear about it any more, so
    // the promise has to end rather than hang on the screen forever.
    settle((p) => p.reject(new Error('disconnected')))
  }, [settle])

  const { isConnected, sendMessage } = useWebSocket({ enabled, onMessage, onDisconnect })
  sendRef.current = sendMessage

  const ask = useCallback(
    (input: AskInput) =>
      new Promise<Answer>((resolve, reject) => {
        if (pendingRef.current) {
          reject(new Error('a question is already in flight'))
          return
        }
        const question = input.question.trim()
        const timer = setTimeout(
          () => settle((p) => p.reject(new AnswerTimeout())),
          ANSWER_DEADLINE_MS[input.effort] ?? ANSWER_DEADLINE_MS.medium,
        )
        pendingRef.current = { question, chatId: null, resolve, reject, timer }
        inputRef.current = input
        setStage('understand')
        // The title is the question. It is what the history list shows, and
        // the backend truncates it, so nothing here has to.
        sendMessage('create_chat', { title: question })
      }),
    [sendMessage, settle],
  )

  const value = useMemo<LiveValue>(
    () => ({ isConnected, stage, ask }),
    [isConnected, stage, ask],
  )

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
}

export function useLive(): LiveValue {
  const ctx = useContext(LiveContext)
  if (!ctx) throw new Error('useLive must be used inside <LiveProvider>')
  return ctx
}
