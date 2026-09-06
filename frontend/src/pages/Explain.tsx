import { useCallback, useEffect, useRef, useState } from 'react'
import { ExplanationView } from '../components/ExplanationView'
import { NarrationToggle, type NarrationVoice } from '../components/NarrationToggle'
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
import { explanationFromAnswer, explanationFromChat, listChats, loadChat, toConversation } from '../lib/chats'
import { useI18n } from '../lib/i18n'
import { useLive, type AskStage } from '../lib/live'
import { EXAMPLE_QUESTIONS, PRICES } from '../lib/mockData'
import { useStore } from '../lib/store'
import type { Conversation, Explanation, Lang, LangChoice } from '../lib/types'
import { formatDateTime, formatMoney } from '../lib/utils'

type ViewState = 'idle' | 'generating' | 'result' | 'error'

const STAGE_ORDER: AskStage[] = ['understand', 'write', 'render']

export function Explain() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const { user, explainLang, saveToLibrary, charge } = useStore()
  const { ask, stage, isConnected } = useLive()

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
  const inputRef = useRef<HTMLTextAreaElement>(null)

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
    async (text: string) => {
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
        })
        const explanation = explanationFromAnswer(answer)
        setCurrent(explanation)
        setState('result')
        setConversations((prev) => [
          {
            id: explanation.chatId ?? explanation.id,
            title: asked,
            createdAt: explanation.createdAt,
            explanationId: explanation.chatId ?? explanation.id,
          },
          ...prev.filter((c) => c.id !== explanation.chatId),
        ])
        // A cached answer costs a couple of database reads, so it is not
        // billed - charging for it would penalise exactly what keeps the
        // service affordable.
        if (user?.role === 'teacher' && !explanation.fromCache) {
          charge('explanation', 1, asked.slice(0, 40))
        }
      } catch (error) {
        setFailure(error instanceof Error ? error.message : null)
        setState('error')
      }
    },
    [ask, charge, narration, user?.role, voice],
  )

  function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    void run(question)
  }

  async function openConversation(chatId: string) {
    try {
      const found = explanationFromChat(await loadChat(chatId))
      if (!found) return
      setCurrent(found)
      setQuestion(found.question)
      setState('result')
      setFailure(null)
    } catch {
      // The entry is in the list but unreadable; leave the screen as it was
      // rather than clearing what the reader was looking at.
    }
  }

  function newConversation() {
    setCurrent(null)
    setQuestion('')
    setState('idle')
    setFailure(null)
    inputRef.current?.focus()
  }

  function save() {
    if (!current) return
    saveToLibrary(current)
    setCurrent({ ...current, saved: true })
    toast(t('explain.savedToast'))
  }

  const defaultLangLabel = explainLang === 'kk' ? t('common.kazakh') : t('common.russian')

  // Sample questions are content, so they follow the answer language.
  const exampleLang: Lang = outputLang === 'auto' ? explainLang : outputLang

  const busy = state === 'generating'

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('explain.title')}</h1>
          <p className="page__subtitle">
            {user?.role === 'teacher'
              ? t('explain.costNote', { cost: formatMoney(PRICES.explanation, lang) })
              : defaultLangLabel}
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
              {conversations.map((conversation) => (
                <li key={conversation.id}>
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
                    ]}
                  />
                  <NarrationToggle
                    enabled={narration}
                    voice={voice}
                    onEnabledChange={setNarration}
                    onVoiceChange={setVoice}
                    disabled={busy}
                  />
                </div>
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
                    <Button icon="refresh" onClick={() => void run(current.question)}>
                      {t('explain.askAgain')}
                    </Button>
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
                      onClick={save}
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
                    do next, which a generic sentence cannot. */}
                {failure || t('explain.errorBody')}
              </Alert>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
