/**
 * What drives a student's screens.
 *
 * Two implementations behind one shape: the server one for a real run, and a
 * local one for the teacher's "see it as a student" preview. The screens do
 * not know which they are talking to, which is the point - the preview shows
 * the real thing, not a drawing of it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { QuizError, playState, sendAnswer } from '../api'
import { useQuizSocket, useServerClock } from '../live'
import type {
  PlayEvent,
  PlayQuestion,
  PlayState,
  Quiz,
  QuizQuestion,
  Reveal,
} from '../types'

export interface AnswerInput {
  optionId?: string
  text?: string
  skip?: boolean
}

export interface Feedback {
  question: PlayQuestion
  pickedId: string | null
  typed: string
  skipped: boolean
  /** null when the teacher chose not to show results. */
  correct: boolean | null
  points: number | null
  reveal: Reveal | null
  next: PlayState
}

export interface PlayController {
  state: PlayState | null
  feedback: Feedback | null
  /** How many are in the lobby, as last heard. */
  players: number
  busy: boolean
  failed: boolean
  connected: boolean
  /** Per question id, whether this phone saw it marked right. */
  history: Record<string, boolean | null>
  /** The same verdicts in the order they were given, for the progress strip. */
  trail: Array<boolean | null>
  now: () => number
  answer: (input: AnswerInput) => void
  next: () => void
  refresh: () => void
}

/* ------------------------------------------------------------ server -- */

// The service accepts an answer up to 3s after the deadline (network grace),
// so it only reports a student finished after that; asking sooner is wasted.
const DEADLINE_GRACE_MS = 3300
// How soon to ask again when the moment has passed but the server disagrees.
const RETRY_MS = 450

export function useServerPlayer(token: string | null, onGone: () => void): PlayController {
  const [state, setState] = useState<PlayState | null>(null)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [players, setPlayers] = useState(0)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const [history, setHistory] = useState<Record<string, boolean | null>>({})
  const [trail, setTrail] = useState<Array<boolean | null>>([])
  const { sync, now } = useServerClock()
  const onGoneRef = useRef(onGone)
  onGoneRef.current = onGone

  const apply = useCallback(
    (next: PlayState) => {
      sync(next.serverNow)
      setState(next)
    },
    [sync],
  )

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      apply(await playState(token))
      setFailed(false)
    } catch (error) {
      if (error instanceof QuizError && (error.status === 401 || error.status === 410)) {
        onGoneRef.current()
      } else {
        setFailed(true)
      }
    }
  }, [token, apply])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const hello = useMemo(() => (token ? { type: 'hello', token } : undefined), [token])
  const { connected } = useQuizSocket<PlayEvent>({
    path: '/ws/quiz/play',
    enabled: Boolean(token),
    hello,
    onEvent: (event) => {
      if (event.type === 'state') {
        apply(event.state)
        setPlayers(event.players)
      } else if (event.type === 'lobby') {
        setPlayers(event.players)
      } else if (event.type === 'status') {
        sync(event.serverNow)
        void refresh()
      } else if (event.type === 'kicked') {
        setState((current) => (current ? { ...current, status: 'kicked' } : current))
      } else if (event.type === 'refresh') {
        void refresh()
      }
    },
    onFinal: (code) => {
      if (code === 4403) {
        setState((current) => (current ? { ...current, status: 'kicked' } : current))
      } else {
        onGoneRef.current()
      }
    },
  })

  // Without the socket, ask now and then: the teacher may start or end the
  // quiz while this phone is not listening.
  const status = state?.status
  useEffect(() => {
    if (connected || !token || status === 'kicked') return
    const id = window.setInterval(() => void refresh(), 4000)
    return () => window.clearInterval(id)
  }, [connected, token, status, refresh])

  // The countdown ending and the deadline passing are both moments the
  // server's answer changes; ask when they arrive rather than polling.
  //
  // Keyed on serverNow too, so every answer schedules the next question. A
  // phone that asks a moment early - its offset is only as good as the last
  // round trip - is told "countdown" again, and without this it would never
  // ask a second time: the screen stayed on "1" for good. Seen on a Docker VM
  // whose clock ran 8% slow, which any real network can imitate.
  const startsAt = state?.startsAt
  const deadline = state?.deadline
  const serverNow = state?.serverNow
  useEffect(() => {
    const target =
      status === 'countdown' && startsAt
        ? Date.parse(startsAt)
        : status === 'playing' && deadline
          ? Date.parse(deadline) + DEADLINE_GRACE_MS
          : null
    if (target === null) return
    const left = target - now()
    const wait = left > 0 ? left + 60 : RETRY_MS
    const id = window.setTimeout(() => void refresh(), wait)
    return () => window.clearTimeout(id)
  }, [status, startsAt, deadline, serverNow, now, refresh])

  const answer = useCallback(
    async (input: AnswerInput) => {
      const question = state?.question
      if (!token || !question || busy || feedback) return
      setBusy(true)
      try {
        const reply = await sendAnswer(token, { questionId: question.id, ...input })
        sync(reply.state.serverNow)
        setHistory((h) => ({ ...h, [question.id]: reply.correct }))
        setTrail((list) => {
          // A phone that reloaded mid-quiz does not know its earlier verdicts;
          // those segments stay neutral rather than being guessed.
          const filled = [...list]
          while (filled.length < question.index) filled.push(null)
          filled[question.index] = reply.correct
          return filled
        })
        setFeedback({
          question,
          pickedId: input.optionId ?? null,
          typed: input.text ?? '',
          skipped: Boolean(input.skip),
          correct: reply.correct,
          points: reply.points,
          reveal: reply.reveal,
          next: reply.state,
        })
        setFailed(false)
      } catch (error) {
        if (error instanceof QuizError && error.status === 409) await refresh()
        else if (error instanceof QuizError && error.status === 401) onGoneRef.current()
        else setFailed(true)
      } finally {
        setBusy(false)
      }
    },
    [token, state, busy, feedback, sync, refresh],
  )

  const next = useCallback(() => {
    if (!feedback) return
    apply(feedback.next)
    setFeedback(null)
  }, [feedback, apply])

  return {
    state,
    feedback,
    players,
    busy,
    failed,
    connected,
    history,
    trail,
    now,
    answer: (input) => void answer(input),
    next,
    refresh: () => void refresh(),
  }
}

/* ------------------------------------------------------------- local -- */

const COUNTDOWN_MS = 3200

function normalize(value: string): string {
  return value
    .normalize('NFKC')
    .trim()
    .toLowerCase()
    .replace(/[−–]/g, '-')
    .replace(/(\d)[\s ](?=\d{3}(?!\d))/g, '$1')
    .replace(/(\d),(\d)/g, '$1.$2')
    .replace(/\s+/g, ' ')
    .replace(/[.!]+$/, '')
}

/** The service's marking, approximated for the preview. The server decides for real. */
function markShort(value: string, question: QuizQuestion): boolean {
  const given = normalize(value)
  if (!given) return false
  const unit = normalize(question.unit ?? '')
  const strip = (s: string) => (unit && s.endsWith(unit) ? s.slice(0, -unit.length).trim() : s)
  const accepted = [question.answer ?? '', ...(question.accept ?? [])].map(normalize).filter(Boolean)
  if (accepted.includes(given) || accepted.map(strip).includes(strip(given))) return true
  const asNumber = Number(strip(given).replace(/\s/g, ''))
  return (
    !Number.isNaN(asNumber) &&
    accepted.some((a) => {
      const expected = Number(strip(a).replace(/\s/g, ''))
      return !Number.isNaN(expected) && Math.abs(asNumber - expected) <= 1e-9 * Math.max(1, Math.abs(expected))
    })
  )
}

function shuffled<T>(items: T[]): T[] {
  const copy = [...items]
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[copy[i], copy[j]] = [copy[j], copy[i]]
  }
  return copy
}

interface LocalRun {
  order: QuizQuestion[]
  optionOrder: Record<string, string[]>
  answered: number
  correct: number
  score: number
  streak: number
  bestStreak: number
  results: Record<string, boolean>
  startsAt: number
}

/**
 * The preview: the same screens, run against the quiz as it is in the editor,
 * with nothing sent anywhere. Questions that are not finished are skipped -
 * the server would refuse to open a run with them anyway.
 */
export function useLocalPlayer(quiz: Quiz, name: string): PlayController & { restart: () => void } {
  const playable = useMemo(
    () => quiz.questions.filter((q) => !quiz.problems[q.id]?.length),
    [quiz],
  )
  const settings = quiz.settings

  const fresh = useCallback((): LocalRun => {
    const order = settings.shuffleQuestions ? shuffled(playable) : playable
    const optionOrder: Record<string, string[]> = {}
    order.forEach((q) => {
      const ids = (q.options ?? []).map((o) => o.id)
      optionOrder[q.id] = settings.shuffleOptions ? shuffled(ids) : ids
    })
    return {
      order,
      optionOrder,
      answered: 0,
      correct: 0,
      score: 0,
      streak: 0,
      bestStreak: 0,
      results: {},
      startsAt: Date.now() + COUNTDOWN_MS,
    }
  }, [playable, settings.shuffleOptions, settings.shuffleQuestions])

  const [run, setRun] = useState<LocalRun>(fresh)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [, setTick] = useState(0)

  useEffect(() => {
    const wait = run.startsAt - Date.now()
    if (wait <= 0) return
    const id = window.setTimeout(() => setTick((t) => t + 1), wait + 30)
    return () => window.clearTimeout(id)
  }, [run.startsAt])

  const stateOf = useCallback(
    (r: LocalRun): PlayState => {
      const at = Date.now()
      const total = r.order.length
      const done = r.answered >= total
      const current = done ? null : r.order[r.answered]
      const status = at < r.startsAt ? 'countdown' : done ? 'finished' : 'playing'
      const byId = new Map((current?.options ?? []).map((o) => [o.id, o]))
      return {
        status,
        sessionStatus: 'running',
        title: quiz.title,
        questionCount: total,
        showResults: settings.showResults,
        leaderboard: false,
        serverNow: new Date(at).toISOString(),
        startsAt: new Date(r.startsAt).toISOString(),
        deadline: null,
        player: { id: 'preview', name },
        progress: {
          answered: r.answered,
          total,
          score: r.score,
          correct: r.correct,
          streak: r.streak,
        },
        question:
          status === 'playing' && current
            ? {
                id: current.id,
                type: current.type,
                text: current.text,
                index: r.answered,
                total,
                options:
                  current.type === 'choice'
                    ? (r.optionOrder[current.id] ?? [])
                        .map((id) => byId.get(id))
                        .filter((o): o is NonNullable<typeof o> => Boolean(o))
                        .map((o) => ({ id: o.id, text: o.text }))
                    : undefined,
                unit: current.unit,
              }
            : null,
        result: done
          ? {
              answered: r.answered,
              total,
              waiting: false,
              ...(settings.showResults
                ? {
                    score: r.score,
                    correct: r.correct,
                    bestStreak: r.bestStreak,
                    answers: r.order.map((q) => ({ questionId: q.id, correct: r.results[q.id] ?? null })),
                  }
                : {}),
            }
          : null,
      }
    },
    [quiz.title, settings.showResults, name],
  )

  const answer = useCallback(
    (input: AnswerInput) => {
      if (feedback) return
      const question = run.order[run.answered]
      if (!question) return
      const right = input.skip
        ? false
        : question.type === 'choice'
          ? input.optionId === question.correct
          : markShort(input.text ?? '', question)
      const streak = right ? run.streak + 1 : 0
      const points = right ? 100 + Math.min(50, (streak - 1) * 10) : 0
      const nextRun: LocalRun = {
        ...run,
        answered: run.answered + 1,
        correct: run.correct + (right ? 1 : 0),
        score: run.score + points,
        streak,
        bestStreak: Math.max(run.bestStreak, streak),
        results: { ...run.results, [question.id]: right },
      }
      const shown = stateOf(run).question
      if (!shown) return
      setFeedback({
        question: shown,
        pickedId: input.optionId ?? null,
        typed: input.text ?? '',
        skipped: Boolean(input.skip),
        correct: settings.showResults ? right : null,
        points: settings.showResults ? points : null,
        reveal: settings.showResults
          ? {
              explanation: question.explanation,
              correctOptionId: question.type === 'choice' ? question.correct : undefined,
              answer:
                question.type === 'short'
                  ? `${question.answer ?? ''} ${question.unit ?? ''}`.trim()
                  : undefined,
            }
          : null,
        next: stateOf(nextRun),
      })
      setRun(nextRun)
    },
    [feedback, run, settings.showResults, stateOf],
  )

  const history = useMemo(
    () => Object.fromEntries(Object.entries(run.results).map(([k, v]) => [k, settings.showResults ? v : null])),
    [run.results, settings.showResults],
  )
  const trail = useMemo(
    () => run.order.slice(0, run.answered).map((q) => (settings.showResults ? run.results[q.id] : null)),
    [run.order, run.answered, run.results, settings.showResults],
  )
  const next = useCallback(() => setFeedback(null), [])

  return {
    state: stateOf(run),
    feedback,
    players: 1,
    busy: false,
    failed: false,
    connected: true,
    history,
    trail,
    now: () => Date.now(),
    answer,
    next,
    refresh: () => setTick((t) => t + 1),
    restart: () => {
      setFeedback(null)
      setRun(fresh())
    },
  }
}
