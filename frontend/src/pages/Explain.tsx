import { useRef, useState } from 'react'
import { ExplanationView } from '../components/ExplanationView'
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
import { useI18n } from '../lib/i18n'
import {
  generateExplanation,
  renderAnimation,
  type GenerationStage,
  type Outcome,
} from '../lib/mockApi'
import { EXAMPLE_QUESTIONS, PRICES } from '../lib/mockData'
import { useStore } from '../lib/store'
import type { Explanation, Lang, LangChoice } from '../lib/types'
import { formatDateTime, formatMoney } from '../lib/utils'

type ViewState = 'idle' | 'generating' | 'result' | 'error'

const STAGE_ORDER: GenerationStage[] = ['understand', 'write', 'render']

export function Explain() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const {
    user,
    explainLang,
    conversations,
    explanations,
    startConversation,
    saveToLibrary,
    recordExplanation,
    charge,
  } = useStore()

  const [question, setQuestion] = useState('')
  const [outputLang, setOutputLang] = useState<LangChoice>('auto')
  const [state, setState] = useState<ViewState>('idle')
  const [stage, setStage] = useState<GenerationStage>('understand')
  const [current, setCurrent] = useState<Explanation | null>(null)
  const [demoOutcome, setDemoOutcome] = useState<Outcome>('ok')
  const [reRendering, setReRendering] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const steps: ProgressStep[] = STAGE_ORDER.map((key) => ({
    key,
    label: t(`explain.stage.${key}` as const),
  }))

  async function run(text: string) {
    if (!text.trim()) return
    setState('generating')
    setStage('understand')
    setCurrent(null)
    try {
      const explanation = await generateExplanation({
        question: text,
        lang: outputLang === 'auto' ? 'auto' : outputLang,
        outcome: demoOutcome,
        onStage: setStage,
      })
      setCurrent(explanation)
      setState('result')
      startConversation(explanation)
      if (user?.role === 'teacher') {
        charge('explanation', 1, explanation.question.slice(0, 40))
      }
    } catch {
      setState('error')
    }
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    void run(question)
  }

  function openConversation(explanationId: string) {
    const found = explanations[explanationId]
    if (!found) return
    setCurrent(found)
    setQuestion(found.question)
    setState('result')
  }

  function newConversation() {
    setCurrent(null)
    setQuestion('')
    setState('idle')
    inputRef.current?.focus()
  }

  async function retryRender() {
    if (!current) return
    setReRendering(true)
    const rendered = await renderAnimation(current)
    setCurrent(rendered)
    recordExplanation(rendered)
    setReRendering(false)
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

      <div className="demo-bar">
        <Icon name="sliders" size={16} />
        <span>{t('explain.demoHint')}</span>
        <SegmentedControl
          label={t('explain.demoLabel')}
          value={demoOutcome}
          onChange={setDemoOutcome}
          options={[
            { value: 'ok', label: t('explain.demo.ok') },
            { value: 'partial', label: t('explain.demo.partial') },
            { value: 'error', label: t('explain.demo.error') },
          ]}
        />
      </div>

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
                      current?.id === conversation.explanationId
                        ? 'history__item is-active'
                        : 'history__item'
                    }
                    aria-current={
                      current?.id === conversation.explanationId ? 'true' : undefined
                    }
                    onClick={() => openConversation(conversation.explanationId)}
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
                <Button
                  type="submit"
                  variant="primary"
                  icon="sparkle"
                  loading={state === 'generating'}
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

            {state === 'generating' ? (
              <Card as="section" elevation="raised" className="stack stack-lg">
                <div className="stack stack-sm">
                  <h2 className="card__title">{t('explain.generatingTitle')}</h2>
                  <p className="text-sm text-secondary">{t('explain.generatingBody')}</p>
                </div>
                <ProgressSteps steps={steps} activeIndex={STAGE_ORDER.indexOf(stage)} />
              </Card>
            ) : null}

            {state === 'result' && current ? (
              <Card as="section" elevation="raised">
                <ExplanationView
                  explanation={current}
                  autoPlay
                  partialAction={
                    <Button
                      icon="refresh"
                      loading={reRendering}
                      onClick={() => void retryRender()}
                    >
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
                {t('explain.errorBody')}
              </Alert>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
