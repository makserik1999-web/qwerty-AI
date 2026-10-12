import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ExplanationView } from '../components/ExplanationView'
import { NarrationToggle, type NarrationVoice } from '../components/NarrationToggle'
import { EffortPicker } from '../components/EffortPicker'
import { VideoLengthPicker } from '../components/VideoLengthPicker'
import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  Icon,
  ProgressSteps,
  SegmentedControl,
  Textarea,
  useToast,
  type ProgressStep,
} from '../components/ui'
import {
  deleteChat,
  explanationFromAnswer,
  explanationFromChat,
  listChats,
  loadChat,
  toConversation,
} from '../lib/chats'
import { getPlan, refusalKey, type PlanSummary } from '../lib/api'
import { useI18n } from '../lib/i18n'
import {
  AgentError,
  AnswerTimeout,
  useLive,
  type AskStage,
  type Effort,
  type VideoLength,
} from '../lib/live'
import { EXAMPLE_QUESTIONS } from '../lib/mockData'
import { useStore } from '../lib/store'
import type { Conversation, ExplainLang, Explanation, LangChoice } from '../lib/types'
import { formatDateTime } from '../lib/utils'

type ViewState = 'idle' | 'generating' | 'result' | 'error'

const STAGE_ORDER: AskStage[] = ['understand', 'write', 'render']

export function Explain() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const { user, explainLang, saveToLibrary } = useStore()
  const { ask, stage, isConnected } = useLive()

  // What the plan has left, shown by the button so a refusal is never the
  // first a teacher hears of a limit.
  const [plan, setPlan] = useState<PlanSummary | null>(null)
  const refreshPlan = useCallback(async () => {
    if (user?.role !== 'teacher') return
    try {
      setPlan((await getPlan()).plan)
    } catch {
      /* the hint is optional; the server still enforces the limit */
    }
  }, [user?.role])
  useEffect(() => {
    void refreshPlan()
  }, [refreshPlan])

  const [question, setQuestion] = useState('')
  const [outputLang, setOutputLang] = useState<LangChoice>('auto')
  const [state, setState] = useState<ViewState>('idle')
  const [current, setCurrent] = useState<Explanation | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [conversations, setConversations] = useState<Conversation[]>([])
  // On per the plan, and chosen per question rather than in settings: it
  // changes what the answer is, not how the app behaves.
  const [narration, setNarration] = useState(true)
  const [voice, setVoice] = useState<NarrationVoice>('aigul')
  // Medium by default. Before this control existed the length was
  // whatever the model happened to write - measured between 60 and 96
  // seconds for the same kind of question - and nobody chose it.
  const [videoLength, setVideoLength] = useState<VideoLength>('medium')
  // Medium, which is 720p30. The old default was manim's own 480p15 -
  // never chosen by anyone, and visibly choppy on a classroom projector.
  const [effort, setEffort] = useState<Effort>('medium')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [searchParams, setSearchParams] = useSearchParams()

  /* A question handed over by another screen - the quiz results' "explain
     this with a video" - lands in the box ready to send, not sent: asking
     costs a generation, and that is the teacher's decision to make. */
  useEffect(() => {
    const handed = searchParams.get('q')
    if (!handed) return
    setQuestion(handed.slice(0, 600))
    setSearchParams({}, { replace: true })
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }, [searchParams, setSearchParams])

  const steps: ProgressStep[] = STAGE_ORDER.map((key) => ({
    key,
    label: t(`explain.stage.${key}` as const),
  }))

  /* The history is the chat list. Loaded once; new questions are added to it
     as they are answered, so the list does not need re-fetching each time. */
  useEffect(() => {
    let cancelled = false
    listChats()
      .then((chats) => {
        if (!cancelled) setConversations(chats.map(toConversation))
      })
      .catch(() => {
        // An unreadable history is not a reason to block asking a question.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const run = useCallback(
    async (text: string, options: { force?: boolean } = {}) => {
      const asked = text.trim()
      if (!asked) return
      setState('generating')
      setCurrent(null)
      setFailure(null)
      try {
        const answer = await ask({
          question: asked,
          narration,
          narrationVoice: voice,
          videoLength,
          effort,
          forceRegenerate: options.force,
          ...(outputLang === 'auto' ? {} : { outputLanguage: outputLang }),
        })
        const explanation = explanationFromAnswer(answer)
        setCurrent(explanation)
        setState('result')
        void refreshPlan()
        setConversations((prev) => [
          {
            id: explanation.chatId ?? explanation.id,
            title: asked,
            createdAt: explanation.createdAt,
            explanationId: explanation.chatId ?? explanation.id,
          },
          ...prev.filter((c) => c.id !== explanation.chatId),
        ])
      } catch (error) {
        // Only the server's own words are worth showing: they say what to do
        // next - the agent is down, the quota is spent. A dropped socket
        // produces an internal string ("disconnected") that means nothing to
        // the person reading it.
        // The render is not cancelled by a timeout - it finishes and is
        // saved - so the message points at the history rather than implying
        // the work was lost.
        // A refusal with a code is said in the reader's language; the
        // server's sentence is English.
        const refusal = error instanceof AgentError ? refusalKey(error.code, 'videos') : null
        setFailure(
          error instanceof AnswerTimeout
            ? t('explain.timedOut')
            : error instanceof AgentError && error.code === 'teacher_only'
              ? t('explain.teacherOnly')
              : refusal
                ? t(refusal)
                : error instanceof AgentError
                  ? error.message
                  : null,
        )
        setState('error')
        // Whatever happened, the plan's count may have moved.
        void refreshPlan()
      }
    },
    [ask, effort, narration, outputLang, refreshPlan, t, voice, videoLength],
  )

  function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    void run(question)
  }

  async function openConversation(chatId: string) {
    try {
      const chat = await loadChat(chatId)
      const found = explanationFromChat(chat)
      if (!found) {
        /* A question with no answer. The history lists chats, and a chat is
           created before the question is sent - so one that was refused, lost
           or never finished is in the list with the question as its title and
           nothing behind it.

           This used to return here, which meant clicking the entry did
           NOTHING: no answer, no message, not even a change of selection. The
           reader is left to conclude the interface is broken, when in fact
           their question is the thing that went missing. Put it back in the
           box and say so - the error card's Retry then asks it again, which
           is what they wanted from the click. */
        setCurrent(null)
        setQuestion(chat.title)
        setFailure(t('explain.noAnswerYet'))
        setState('error')
        return
      }
      setCurrent(found)
      setQuestion(found.question)
      setState('result')
      setFailure(null)
    } catch {
      // The entry is in the list but unreadable. Say so rather than swallowing
      // it, or this is the same dead click by a different route.
      setFailure(t('explain.historyUnreadable'))
      setState('error')
    }
  }

  async function removeConversation(chatId: string) {
    if (!window.confirm(t('explain.deleteConfirm'))) return
    try {
      // Awaited before the row goes: a list that drops an entry and then has
      // it back on the next reload is worse than one that never dropped it.
      await deleteChat(chatId)
      setConversations((prev) => prev.filter((c) => c.explanationId !== chatId))
      // Only if the reader was looking at the thing just deleted. Clearing the
      // screen for an unrelated row would throw away what they were reading.
      if (current?.chatId === chatId) {
        setCurrent(null)
        setState('idle')
        setFailure(null)
      }
      toast(t('explain.deletedToast'))
    } catch {
      setFailure(t('explain.deleteFailed'))
      setState('error')
    }
  }

  function newConversation() {
    setCurrent(null)
    setQuestion('')
    setState('idle')
    setFailure(null)
    inputRef.current?.focus()
  }

  async function save() {
    if (!current) return
    try {
      // Awaited before the button changes: a Save that says "saved" and then
      // is not there tomorrow is the bug this whole screen had.
      await saveToLibrary(current)
      setCurrent({ ...current, saved: true })
      toast(t('explain.savedToast'))
    } catch (error) {
      setFailure(error instanceof AgentError ? error.message : null)
      setState('error')
    }
  }

  const defaultLangLabel = explainLang === 'kk' ? t('common.kazakh') : t('common.russian')

  // Sample questions are content, so they follow the answer language.
  const exampleLang: ExplainLang = outputLang === 'auto' ? explainLang : outputLang

  const busy = state === 'generating'

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('explain.title')}</h1>
          <p className="page__subtitle">
            {user?.role === 'teacher' ? defaultLangLabel : t('explain.studentNote')}
          </p>
        </div>
        <Button icon="plus" onClick={newConversation}>
          {t('explain.newChat')}
        </Button>
      </header>

      {/* The socket carries the question, so a dropped one is worth saying out
          loud - otherwise pressing the button appears to do nothing. */}
      {!isConnected ? <Alert tone="warning">{t('explain.offline')}</Alert> : null}

      <div className="split split--history">
        {/* History ---------------------------------------------------------- */}
        <Card as="section" elevation="flat" className="history">
          <h2 className="history__title">{t('explain.history')}</h2>
          {conversations.length === 0 ? (
            <p className="text-sm text-secondary">{t('explain.historyEmpty')}</p>
          ) : (
            <ul className="history__list">
              {/* Two buttons side by side rather than one inside the other: a
                  button nested in a button is invalid markup, and the delete
                  would inherit the open click. */}
              {conversations.map((conversation) => (
                <li key={conversation.id} className="history__row">
                  <button
                    type="button"
                    className={
                      current?.chatId === conversation.explanationId
                        ? 'history__item is-active'
                        : 'history__item'
                    }
                    aria-current={
                      current?.chatId === conversation.explanationId ? 'true' : undefined
                    }
                    onClick={() => void openConversation(conversation.explanationId)}
                  >
                    <span className="history__item-title">{conversation.title}</span>
                    <span className="caption">
                      {formatDateTime(conversation.createdAt, lang)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="history__delete"
                    // The row already reads out the question; without this the
                    // button is announced as nothing at all.
                    aria-label={t('explain.deleteEntry', { title: conversation.title })}
                    title={t('explain.delete')}
                    onClick={() => void removeConversation(conversation.explanationId)}
                  >
                    <Icon name="trash" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Workspace -------------------------------------------------------- */}
        <div className="stack stack-lg">
          <Card as="section" elevation="raised">
            <form className="stack stack-md" onSubmit={onSubmit}>
              <Field label={t('explain.inputLabel')}>
                {(props) => (
                  <Textarea
                    {...props}
                    ref={inputRef}
                    value={question}
                    rows={3}
                    placeholder={t('explain.placeholder')}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                        event.preventDefault()
                        void run(question)
                      }
                    }}
                  />
                )}
              </Field>

              <div className="row row-wrap row-between">
                <div className="row row-wrap">
                  <SegmentedControl
                    label={t('explain.langLabel')}
                    value={outputLang}
                    onChange={setOutputLang}
                    options={[
                      { value: 'auto', label: t('common.auto') },
                      { value: 'kk', label: t('common.kazakh') },
                      { value: 'ru', label: t('common.russian') },
                      { value: 'en', label: t('common.english') },
                    ]}
                  />
                  {/* How a new video is made. A student does not make one -
                      the server refuses - so offering these to them would be
                      a control that does nothing. */}
                  {user?.role === 'teacher' ? (
                    <>
                      <NarrationToggle
                        enabled={narration}
                        voice={voice}
                        onEnabledChange={setNarration}
                        onVoiceChange={setVoice}
                        disabled={busy}
                      />
                      <VideoLengthPicker
                        value={videoLength}
                        onChange={setVideoLength}
                        disabled={busy}
                      />
                      <EffortPicker
                        value={effort}
                        onChange={setEffort}
                        disabled={busy}
                      />
                    </>
                  ) : null}
                </div>
                {plan && plan.kind !== 'free' && plan.available.videos !== null ? (
                  <span className="caption explain__plan-hint">
                    {t('plan.left.videos')}: {plan.available.videos}
                  </span>
                ) : null}
                <Button
                  type="submit"
                  variant="primary"
                  icon="sparkle"
                  loading={busy}
                  disabled={!question.trim()}
                >
                  {t('explain.submit')}
                </Button>
              </div>
            </form>
          </Card>

          {/* Async state changes are announced from this region. */}
          <div aria-live="polite" aria-atomic="true" className="stack stack-lg">
            {state === 'idle' ? (
              <Card as="section" elevation="flat">
                <EmptyState
                  icon="lightbulb"
                  title={t('explain.emptyTitle')}
                  body={t('explain.emptyBody')}
                  level={2}
                />
                <div className="stack stack-sm examples">
                  <h3 className="card__subtitle">{t('explain.examplesTitle')}</h3>
                  <ul className="examples__list">
                    {EXAMPLE_QUESTIONS[exampleLang].map((example) => (
                      <li key={example}>
                        <button
                          type="button"
                          className="examples__item"
                          onClick={() => {
                            setQuestion(example)
                            void run(example)
                          }}
                        >
                          <Icon name="arrowRight" size={16} />
                          {example}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </Card>
            ) : null}

            {busy ? (
              <Card as="section" elevation="raised" className="stack stack-lg">
                <div className="stack stack-sm">
                  <h2 className="card__title">{t('explain.generatingTitle')}</h2>
                  <p className="text-sm text-secondary">{t('explain.generatingBody')}</p>
                </div>
                <ProgressSteps
                  steps={steps}
                  activeIndex={Math.max(0, STAGE_ORDER.indexOf(stage ?? 'understand'))}
                />
              </Card>
            ) : null}

            {state === 'result' && current ? (
              <Card as="section" elevation="raised">
                <ExplanationView
                  explanation={current}
                  autoPlay
                  askAgainAction={
                    // Forced: asking the same words again would find the
                    // same library answer.
                    <Button icon="refresh" onClick={() => void run(current.question, { force: true })}>
                      {t('explain.askAgain')}
                    </Button>
                  }
                  onMakeMine={
                    user?.role === 'teacher'
                      ? () => void run(current.question, { force: true })
                      : undefined
                  }
                  partialAction={
                    <Button icon="refresh" onClick={() => void run(current.question)}>
                      {t('explain.partialRetry')}
                    </Button>
                  }
                  actions={
                    <Button
                      variant={current.saved ? 'secondary' : 'primary'}
                      icon={current.saved ? 'check' : 'book'}
                      disabled={current.saved}
                      onClick={() => void save()}
                    >
                      {current.saved
                        ? t('explain.savedToLibrary')
                        : t('explain.saveToLibrary')}
                    </Button>
                  }
                />
              </Card>
            ) : null}

            {state === 'error' ? (
              <Alert
                tone="error"
                title={t('explain.errorTitle')}
                action={
                  <Button icon="refresh" onClick={() => void run(question)}>
                    {t('common.retry')}
                  </Button>
                }
              >
                {/* The server's own words when there are any - "the agent is
                    not available", a quota refusal - because they say what to
                    do next, which a generic sentence cannot. Otherwise the
                    generic sentence, which at least is in the right language. */}
                {failure || t('explain.errorBody')}
              </Alert>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
