/**
 * The quiz editor.
 *
 * Everything is edited in place and saved as it is typed; there is no Save
 * button to forget. Questions are reordered by dragging their handle (or from
 * the card's menu, which is the keyboard's way), a deleted one can be brought
 * back for a few seconds, and the panel on the right is where a run begins.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Icon,
  Menu,
  Modal,
  SegmentedControl,
  Select,
  Skeleton,
  useToast,
} from '../../components/ui'
import { useI18n } from '../../lib/i18n'
import { GRADES, SUBJECTS } from '../../lib/mockData'
import { useStore } from '../../lib/store'
import type { Lang, SubjectId } from '../../lib/types'
import { cx, formatDateTime } from '../../lib/utils'
import { QuizError, draftQuestions, loadQuiz, openRun, saveQuiz } from '../api'
import { QuestionCard, type CardAction } from '../components/QuestionCard'
import { RunPanel } from '../components/RunPanel'
import { blankChoice, blankShort, blankTrueFalse, duplicate, fromDraft, problemsOf } from '../edit'
import { Glyph } from '../glyphs'
import { useLocalPlayer } from '../play/controller'
import { PlayerView } from '../play/PlayerView'
import type { ProblemCode, Quiz, QuizQuestion, QuizSettings } from '../types'
import '../quiz.css'

const MAX_QUESTIONS = 50
const SAVE_DELAY_MS = 700
const UNDO_MS = 6000
const EASE = 'cubic-bezier(0.16, 1, 0.3, 1)'

type SaveState = 'idle' | 'saving' | 'failed'

function fieldsOf(quiz: Quiz) {
  return {
    title: quiz.title,
    subject: quiz.subject,
    grade: quiz.grade,
    lang: quiz.lang,
    topic: quiz.topic,
    questions: quiz.questions,
    settings: quiz.settings,
  }
}

export function QuizEditor() {
  const { quizId = '' } = useParams()
  const navigate = useNavigate()
  const { t, lang: uiLang } = useI18n()
  const { toast } = useToast()

  const [quiz, setQuiz] = useState<Quiz | null>(null)
  const [failed, setFailed] = useState(false)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [flash, setFlash] = useState<string | null>(null)
  const [gone, setGone] = useState<{ question: QuizQuestion; index: number } | null>(null)
  const [busy, setBusy] = useState<Set<string>>(new Set())
  const [drafting, setDrafting] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [classLabel, setClassLabel] = useState('')
  const [starting, setStarting] = useState(false)
  const [dragId, setDragId] = useState<string | null>(null)

  /* ------------------------------------------------------- loading -- */

  useEffect(() => {
    let cancelled = false
    loadQuiz(quizId)
      .then((loaded) => {
        if (cancelled) return
        setQuiz(loaded)
        setSavedAt(loaded.updatedAt)
        // Questions that arrived finished show their problems at once;
        // new ones only after they have been left, not while being written.
        setTouched(new Set(loaded.questions.map((q) => q.id)))
        const last = loaded.runs?.find((run) => run.classLabel)
        if (last) setClassLabel(last.classLabel)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [quizId])

  /* -------------------------------------------------------- saving -- */

  const latest = useRef<Quiz | null>(null)
  latest.current = quiz
  const dirty = useRef(false)
  const inflight = useRef<Promise<void> | null>(null)

  const flush = useCallback(async (): Promise<void> => {
    if (inflight.current) {
      await inflight.current
      return flush()
    }
    if (!dirty.current || !latest.current) return
    dirty.current = false
    const snapshot = latest.current
    setSaveState('saving')
    const run = saveQuiz(snapshot.id, fieldsOf(snapshot))
      .then((saved) => {
        setSaveState('idle')
        setSavedAt(saved.updatedAt)
      })
      .catch(() => {
        dirty.current = true
        setSaveState('failed')
      })
      .finally(() => {
        inflight.current = null
      })
    inflight.current = run
    await run
  }, [])

  useEffect(() => {
    if (!dirty.current) return
    const id = window.setTimeout(() => void flush(), SAVE_DELAY_MS)
    return () => window.clearTimeout(id)
  }, [quiz, flush])

  useEffect(() => () => void flush(), [flush])

  useEffect(() => {
    const onLeave = (event: BeforeUnloadEvent) => {
      if (dirty.current || inflight.current) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', onLeave)
    return () => window.removeEventListener('beforeunload', onLeave)
  }, [])

  const edit = useCallback((change: (current: Quiz) => Quiz) => {
    setQuiz((current) => {
      if (!current) return current
      dirty.current = true
      return change(current)
    })
  }, [])

  const setQuestion = useCallback(
    (question: QuizQuestion) =>
      edit((q) => ({ ...q, questions: q.questions.map((x) => (x.id === question.id ? question : x)) })),
    [edit],
  )

  const setSettings = useCallback(
    (patch: Partial<QuizSettings>) => edit((q) => ({ ...q, settings: { ...q.settings, ...patch } })),
    [edit],
  )

  /* ---------------------------------------------------- questions -- */

  const problems = useMemo(() => {
    const found: Record<string, ProblemCode[]> = {}
    quiz?.questions.forEach((q) => {
      const codes = problemsOf(q)
      if (codes.length) found[q.id] = codes
    })
    return found
  }, [quiz?.questions])

  const canDraft = Boolean(
    quiz &&
      SUBJECTS.includes(quiz.subject as SubjectId) &&
      quiz.grade >= 5 &&
      (quiz.lang === 'kk' || quiz.lang === 'ru') &&
      (quiz.topic || quiz.title).trim(),
  )

  function reveal(id: string) {
    window.requestAnimationFrame(() => {
      const card = cardEls.current.get(id)
      card?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      document.getElementById(`q-text-${id}`)?.focus({ preventScroll: true })
    })
  }

  function add(kind: 'choice' | 'two' | 'short') {
    if (!quiz || quiz.questions.length >= MAX_QUESTIONS) return
    const question =
      kind === 'choice' ? blankChoice() : kind === 'two' ? blankTrueFalse(quiz.lang) : blankShort()
    edit((q) => ({ ...q, questions: [...q.questions, question] }))
    reveal(question.id)
  }

  useEffect(() => {
    if (!gone) return
    const id = window.setTimeout(() => setGone(null), UNDO_MS)
    return () => window.clearTimeout(id)
  }, [gone])

  useEffect(() => {
    if (!flash) return
    const id = window.setTimeout(() => setFlash(null), 1500)
    return () => window.clearTimeout(id)
  }, [flash])

  function draftSpec(count: number, mix: 'choice' | 'mixed' | 'short') {
    const current = latest.current as Quiz
    return {
      subject: current.subject as SubjectId,
      grade: current.grade,
      topic: (current.topic || current.title).trim().slice(0, 200),
      lang: current.lang as Lang,
      count,
      mix,
      difficulty: 'medium' as const,
      avoid: current.questions.map((q) => q.text.trim()).filter(Boolean).slice(0, 40),
    }
  }

  function draftFailure(error: unknown): string {
    if (error instanceof QuizError && error.status === 429) return t('quiz.new.errLimit')
    if (error instanceof QuizError && error.status === 503) return t('quiz.new.errUnavailable')
    return t('quiz.edit.draftFailed')
  }

  async function replace(question: QuizQuestion) {
    setBusy((set) => new Set(set).add(question.id))
    try {
      const [draft] =
        (await draftQuestions(draftSpec(1, question.type === 'short' ? 'short' : 'choice'))) ?? []
      if (draft) setQuestion(fromDraft(draft as Record<string, unknown>, question.id))
    } catch (error) {
      toast(draftFailure(error), 'error')
    } finally {
      setBusy((set) => {
        const next = new Set(set)
        next.delete(question.id)
        return next
      })
    }
  }

  async function writeMore(count: number) {
    setDrafting(true)
    try {
      const drafts = (await draftQuestions(draftSpec(count, 'mixed'))) ?? []
      const added = drafts.map((d) => fromDraft(d as Record<string, unknown>))
      edit((q) => ({ ...q, questions: [...q.questions, ...added].slice(0, MAX_QUESTIONS) }))
      toast(t('quiz.edit.added', { n: added.length }))
    } catch (error) {
      toast(draftFailure(error), 'error')
    } finally {
      setDrafting(false)
    }
  }

  function onAction(question: QuizQuestion, index: number, action: CardAction) {
    if (action === 'duplicate') {
      const copy = duplicate(question)
      edit((q) => {
        const list = [...q.questions]
        list.splice(index + 1, 0, copy)
        return { ...q, questions: list.slice(0, MAX_QUESTIONS) }
      })
      reveal(copy.id)
    } else if (action === 'up' || action === 'down') {
      const to = action === 'up' ? index - 1 : index + 1
      edit((q) => {
        const list = [...q.questions]
        const [moved] = list.splice(index, 1)
        list.splice(to, 0, moved)
        return { ...q, questions: list }
      })
    } else if (action === 'replace') {
      void replace(question)
    } else if (action === 'delete') {
      edit((q) => ({ ...q, questions: q.questions.filter((x) => x.id !== question.id) }))
      setGone({ question, index })
    }
  }

  function undoDelete() {
    if (!gone) return
    const { question, index } = gone
    edit((q) => {
      const list = [...q.questions]
      list.splice(Math.min(index, list.length), 0, question)
      return { ...q, questions: list }
    })
    setGone(null)
  }

  /* ------------------------------------------------- drag to reorder -- */

  const listRef = useRef<HTMLOListElement>(null)
  const cardEls = useRef(new Map<string, HTMLElement>())
  const drag = useRef<{ id: string; grab: number; lastY: number } | null>(null)
  const tops = useRef(new Map<string, number>())
  const orderKey = quiz?.questions.map((q) => q.id).join(',') ?? ''
  const lastOrder = useRef(orderKey)

  const placeDragged = useCallback(() => {
    const d = drag.current
    const list = listRef.current
    const card = d ? cardEls.current.get(d.id) : undefined
    if (!d || !list || !card) return
    const wanted = d.lastY - list.getBoundingClientRect().top - d.grab
    card.style.transform = `translateY(${wanted - card.offsetTop}px)`
  }, [])

  // FLIP: when the order changes, every card that moved glides from where it
  // was - except the one being dragged, which follows the pointer instead.
  useLayoutEffect(() => {
    const reordered = lastOrder.current !== orderKey
    lastOrder.current = orderKey
    cardEls.current.forEach((card, id) => {
      const before = tops.current.get(id)
      const now = card.offsetTop
      if (reordered && before !== undefined && before !== now && id !== drag.current?.id) {
        card.animate(
          [{ transform: `translateY(${before - now}px)` }, { transform: 'translateY(0)' }],
          { duration: 280, easing: EASE },
        )
      }
      tops.current.set(id, now)
    })
    placeDragged()
  })

  function onHandleDown(id: string, event: React.PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return
    const card = cardEls.current.get(id)
    if (!card) return
    event.preventDefault()
    drag.current = { id, grab: event.clientY - card.getBoundingClientRect().top, lastY: event.clientY }
    setDragId(id)

    const onMove = (move: PointerEvent) => {
      const d = drag.current
      const list = listRef.current
      const current = latest.current
      if (!d || !list || !current) return
      d.lastY = move.clientY
      placeDragged()
      const dragged = cardEls.current.get(d.id)
      if (!dragged) return
      const center = move.clientY - list.getBoundingClientRect().top - d.grab + dragged.offsetHeight / 2
      let target = 0
      for (const q of current.questions) {
        if (q.id === d.id) continue
        const other = cardEls.current.get(q.id)
        if (other && other.offsetTop + other.offsetHeight / 2 < center) target += 1
      }
      const from = current.questions.findIndex((q) => q.id === d.id)
      if (from !== -1 && target !== from) {
        edit((q) => {
          const list = [...q.questions]
          const [moved] = list.splice(from, 1)
          list.splice(target, 0, moved)
          return { ...q, questions: list }
        })
      }
      if (move.clientY < 90) window.scrollBy(0, -16)
      else if (move.clientY > window.innerHeight - 90) window.scrollBy(0, 16)
    }

    const onUp = () => {
      const d = drag.current
      const card = d ? cardEls.current.get(d.id) : undefined
      if (card) {
        const from = card.style.transform
        card.style.transform = ''
        card.animate([{ transform: from || 'translateY(0)' }, { transform: 'translateY(0)' }], {
          duration: 220,
          easing: EASE,
        })
      }
      drag.current = null
      setDragId(null)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
  }

  /* ---------------------------------------------------------- running -- */

  async function start() {
    if (!quiz || quiz.questions.length === 0) return
    const firstBad = quiz.questions.find((q) => problems[q.id])
    if (firstBad) {
      setTouched(new Set(quiz.questions.map((q) => q.id)))
      setFlash(firstBad.id)
      reveal(firstBad.id)
      return
    }
    setStarting(true)
    try {
      dirty.current = true
      await flush()
      const run = await openRun(quiz.id, quiz.settings, classLabel.trim())
      navigate(`/host/${run.id}`)
    } catch (error) {
      const code = error instanceof QuizError ? error.code : ''
      toast(
        code === 'too_many_open'
          ? t('quiz.edit.tooManyOpen')
          : code === 'quiz_not_ready'
            ? t('quiz.edit.notReady')
            : t('quiz.edit.startFailed'),
        'error',
      )
    } finally {
      setStarting(false)
    }
  }

  /* ----------------------------------------------------------- render -- */

  if (failed) {
    return (
      <div className="page">
        <Alert
          tone="error"
          title={t('quiz.edit.loadFailed')}
          action={<Button onClick={() => navigate('/app/quizzes')}>{t('quiz.host.backToQuizzes')}</Button>}
        >
          {t('quiz.list.loadFailedBody')}
        </Alert>
      </div>
    )
  }

  if (!quiz) {
    return (
      <div className="page">
        <Skeleton height="40px" width="50%" />
        <div className="qe">
          <div className="stack stack-md">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} height="180px" />
            ))}
          </div>
          <Skeleton height="420px" />
        </div>
      </div>
    )
  }

  const problemCount = Object.keys(problems).length
  const questionCount = quiz.questions.length
  const previewQuiz: Quiz = { ...quiz, problems }

  return (
    <div className="page">
      <header className="qe-head">
        <div className="stack stack-sm grow" style={{ minWidth: 0 }}>
          <nav className="qe-crumbs" aria-label={t('quiz.edit.crumbs')}>
            <Link to="/app/quizzes">{t('quiz.list.title')}</Link> / {t('quiz.edit.crumb')}
          </nav>
          <label className="visually-hidden" htmlFor="quiz-title">
            {t('quiz.edit.titleLabel')}
          </label>
          <input
            id="quiz-title"
            className="qe-title"
            value={quiz.title}
            maxLength={120}
            onChange={(event) => edit((q) => ({ ...q, title: event.target.value }))}
          />
          <div className="qe-meta">
            <Select
              aria-label={t('common.subject')}
              value={quiz.subject}
              onChange={(event) => edit((q) => ({ ...q, subject: event.target.value as SubjectId }))}
              options={[
                ...SUBJECTS.map((item) => ({ value: item, label: t(`subject.${item}`) })),
                ...(quiz.subject === 'other' ? [{ value: 'other', label: t('quiz.subject.other') }] : []),
              ]}
            />
            <Select
              aria-label={t('common.grade')}
              value={String(quiz.grade)}
              onChange={(event) => edit((q) => ({ ...q, grade: Number(event.target.value) }))}
              options={GRADES.map((g) => ({ value: String(g), label: t('quiz.list.grade', { n: g }) }))}
            />
            <SegmentedControl
              label={t('common.language')}
              value={quiz.lang === 'ru' ? 'ru' : 'kk'}
              onChange={(value) => edit((q) => ({ ...q, lang: value }))}
              options={[
                { value: 'kk', label: 'ҚАЗ' },
                { value: 'ru', label: 'РУС' },
              ]}
            />
            <span>{t('quiz.list.questions', { n: questionCount })}</span>
            <span
              className={cx('qe-saved', saveState === 'failed' && 'is-failed')}
              role="status"
              aria-live="polite"
            >
              {saveState === 'saving' ? (
                t('quiz.edit.saving')
              ) : saveState === 'failed' ? (
                <>
                  {t('quiz.edit.saveFailed')}
                  <button type="button" className="stage-link" style={{ color: 'inherit' }} onClick={() => void flush()}>
                    {t('common.retry')}
                  </button>
                </>
              ) : savedAt ? (
                <>
                  <Icon name="check" size={14} />
                  {t('quiz.edit.savedAt', { time: formatDateTime(savedAt, uiLang) })}
                </>
              ) : null}
            </span>
          </div>
        </div>
        <div className="row row--actions">
          <Button icon="phone" onClick={() => setPreviewing(true)} disabled={questionCount === problemCount}>
            {t('quiz.edit.preview')}
          </Button>
          <div className="qe-addmenu">
            <Menu
              label={t('quiz.edit.addQuestion')}
              text={t('quiz.edit.addQuestion')}
              items={[
                { key: 'choice', label: t('quiz.edit.addChoice'), onSelect: () => add('choice') },
                { key: 'two', label: t('quiz.edit.addTwo'), onSelect: () => add('two') },
                { key: 'short', label: t('quiz.edit.addShort'), onSelect: () => add('short') },
              ]}
            />
          </div>
        </div>
      </header>

      <div className="qe">
        <div className="stack stack-md">
          {questionCount === 0 && !gone ? (
            <div className="qe-add" style={{ justifyContent: 'center', padding: 'var(--space-2xl)' }}>
              <div className="stack stack-md" style={{ alignItems: 'center', textAlign: 'center' }}>
                <Glyph index={3} size={36} />
                <p className="text-secondary">{t('quiz.edit.emptyBody')}</p>
              </div>
            </div>
          ) : null}

          <ol className="qe-list" ref={listRef} style={{ position: 'relative' }}>
            {quiz.questions.map((question, index) => (
              <QuestionCard
                key={question.id}
                question={question}
                index={index}
                total={questionCount}
                problems={touched.has(question.id) ? problems[question.id] ?? [] : []}
                busy={busy.has(question.id)}
                flash={flash === question.id}
                dragging={dragId === question.id}
                canDraft={canDraft}
                onChange={setQuestion}
                onAction={(action) => onAction(question, index, action)}
                onHandleDown={(event) => onHandleDown(question.id, event)}
                onLeave={() =>
                  setTouched((set) => (set.has(question.id) ? set : new Set(set).add(question.id)))
                }
                cardRef={(element) => {
                  if (element) cardEls.current.set(question.id, element)
                  else cardEls.current.delete(question.id)
                }}
              />
            ))}
          </ol>

          {gone ? (
            <div className="qe-gone" role="status">
              <Icon name="trash" size={16} />
              <span className="grow">{t('quiz.edit.deleted', { n: gone.index + 1 })}</span>
              <Button size="sm" variant="ghost" onClick={undoDelete}>
                {t('quiz.edit.undo')}
              </Button>
            </div>
          ) : null}

          <div className="qe-add">
            <Button icon="plus" variant="ghost" onClick={() => add('choice')}>
              {t('quiz.edit.addChoice')}
            </Button>
            <Button icon="plus" variant="ghost" onClick={() => add('two')}>
              {t('quiz.edit.addTwo')}
            </Button>
            <Button icon="plus" variant="ghost" onClick={() => add('short')}>
              {t('quiz.edit.addShort')}
            </Button>
            {canDraft ? (
              <Button
                icon="listCheck"
                loading={drafting}
                disabled={questionCount >= MAX_QUESTIONS}
                onClick={() => void writeMore(5)}
              >
                {drafting ? t('quiz.edit.writingMore') : t('quiz.edit.writeMore', { n: 5 })}
              </Button>
            ) : null}
          </div>
        </div>

        <RunPanel
          quiz={quiz}
          classLabel={classLabel}
          onClassLabel={setClassLabel}
          onSettings={setSettings}
          problemCount={problemCount}
          onShowProblem={() => {
            const first = quiz.questions.find((q) => problems[q.id])
            if (first) {
              setTouched(new Set(quiz.questions.map((q) => q.id)))
              setFlash(first.id)
              reveal(first.id)
            }
          }}
          starting={starting}
          onStart={() => void start()}
        />
      </div>

      <Modal
        open={previewing}
        title={t('quiz.preview.title')}
        description={t('quiz.preview.body')}
        onClose={() => setPreviewing(false)}
        closeLabel={t('common.close')}
      >
        {previewing ? <PreviewPhone quiz={previewQuiz} /> : null}
      </Modal>
    </div>
  )
}

/** The real student screens, in a phone, run locally against this quiz. */
function PreviewPhone({ quiz }: { quiz: Quiz }) {
  const { user } = useStore()
  const { t } = useI18n()
  const ctl = useLocalPlayer(quiz, user?.name || t('quiz.preview.you'))
  return (
    <div className="qz-phone">
      <div className="qz-phone__screen">
        <div className="stage">
          <div className="qz-band" />
          <div className="stage__bar">
            <Glyph index={0} size={18} />
            <span className="stage__title">{quiz.title}</span>
          </div>
          <div className="stage__body">
            <PlayerView ctl={ctl} preview={{ onRestart: ctl.restart }} />
          </div>
        </div>
      </div>
    </div>
  )
}
