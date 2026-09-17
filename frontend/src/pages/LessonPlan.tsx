import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Icon,
  Input,
  SegmentedControl,
  Select,
  Textarea,
  useToast,
} from '../components/ui'
import { ApiError } from '../lib/api'
import { describeAuthError } from '../lib/authErrors'
import { useI18n } from '../lib/i18n'
import {
  deleteLessonPlan,
  generateLessonPlan,
  listLessonPlans,
  loadLessonPlan,
  plannedMinutes,
  saveLessonPlan,
} from '../lib/lessonPlans'
import { GRADES, SUBJECTS } from '../lib/mockData'
import { useStore } from '../lib/store'
import type {
  Lang,
  LessonPhase,
  LessonPlan as Plan,
  LessonPlanDocument,
  LessonStage,
  SubjectId,
} from '../lib/types'
import { formatDate } from '../lib/utils'

type Status = 'idle' | 'generating' | 'ready' | 'error'

const DURATIONS = [40, 45]
const PHASES: LessonPhase[] = ['start', 'middle', 'end']

/** Editing one field of the document without rebuilding it by hand at every
 *  call site. The plan is one object with a dozen text fields, and a setter
 *  per field would be a dozen near-identical functions. */
type DocField = keyof Omit<LessonPlanDocument, 'objectives' | 'stages' | 'success_criteria'>

export function LessonPlan() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const { explainLang } = useStore()

  const [subject, setSubject] = useState<SubjectId>('physics')
  const [grade, setGrade] = useState(8)
  const [topic, setTopic] = useState('')
  const [section, setSection] = useState('')
  const [planLang, setPlanLang] = useState<Lang>(explainLang === 'ru' ? 'ru' : 'kk')
  const [duration, setDuration] = useState(40)

  const [status, setStatus] = useState<Status>('idle')
  const [failure, setFailure] = useState<string | null>(null)
  const [current, setCurrent] = useState<Plan | null>(null)
  const [doc, setDoc] = useState<LessonPlanDocument | null>(null)
  const [dirty, setDirty] = useState(false)
  const [history, setHistory] = useState<Plan[]>([])

  /* The list of past plans. Loaded once; a new plan is added to it as it is
     made, so the list does not need re-fetching each time. */
  useEffect(() => {
    let cancelled = false
    listLessonPlans()
      .then((items) => {
        if (!cancelled) setHistory(items)
      })
      .catch(() => {
        // An unreadable list is not a reason to block building a plan.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const show = useCallback((plan: Plan) => {
    setCurrent(plan)
    // A copy, so editing the form does not mutate what the list is holding.
    setDoc(JSON.parse(JSON.stringify(plan.plan)) as LessonPlanDocument)
    setDirty(false)
    setStatus('ready')
    setFailure(null)
  }, [])

  async function build(event: React.FormEvent) {
    event.preventDefault()
    const asked = topic.trim()
    if (!asked) return

    setStatus('generating')
    setFailure(null)
    try {
      const plan = await generateLessonPlan({
        subject,
        grade,
        topic: asked,
        lang: planLang,
        duration,
        section: section.trim(),
      })
      show(plan)
      setHistory((prev) => [plan, ...prev])
    } catch (error) {
      // The server's own words when there are any - the generator is down, the
      // hour's quota is spent - because they say what to do next.
      // The server's sentence when it has one: it says whether to wait, to
      // shorten the topic, or that the hour's plans are spent.
      const described = describeAuthError(error, 'auth.error.unknown')
      setFailure(
        error instanceof ApiError && error.detail ? error.detail : t(described.key),
      )
      setStatus('error')
    }
  }

  async function open(id: string) {
    try {
      show(await loadLessonPlan(id))
    } catch {
      setFailure(null)
      setStatus('error')
    }
  }

  async function save() {
    if (!current || !doc) return
    try {
      // Awaited before the button changes: a Save that says "saved" and is
      // gone tomorrow is worse than one that says it failed.
      const saved = await saveLessonPlan(current.id, doc)
      setCurrent(saved)
      setHistory((prev) => prev.map((p) => (p.id === saved.id ? saved : p)))
      setDirty(false)
      toast(t('plan.savedToast'))
    } catch (error) {
      const described = describeAuthError(error, 'auth.error.unknown')
      setFailure(
        error instanceof ApiError && error.detail ? error.detail : t(described.key),
      )
      setStatus('error')
    }
  }

  async function remove(id: string) {
    if (!window.confirm(t('plan.deleteConfirm'))) return
    try {
      await deleteLessonPlan(id)
      setHistory((prev) => prev.filter((p) => p.id !== id))
      if (current?.id === id) {
        setCurrent(null)
        setDoc(null)
        setStatus('idle')
      }
      toast(t('plan.deletedToast'))
    } catch {
      /* the row stays; nothing was lost */
    }
  }

  function edit(field: DocField, value: string) {
    setDoc((prev) => (prev ? { ...prev, [field]: value } : prev))
    setDirty(true)
  }

  function editStage(id: string, field: keyof LessonStage, value: string | number) {
    setDoc((prev) =>
      prev
        ? {
            ...prev,
            stages: prev.stages.map((s) => (s.id === id ? { ...s, [field]: value } : s)),
          }
        : prev,
    )
    setDirty(true)
  }

  const busy = status === 'generating'
  const planned = doc ? plannedMinutes(doc) : 0
  // Against the lesson it was asked for, not against what it was generated as:
  // the teacher may have changed the minutes, and the question they care about
  // is whether the lesson fits.
  const fits = !current || planned === current.duration

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('plan.title')}</h1>
          <p className="page__subtitle">{t('plan.subtitle')}</p>
        </div>
      </header>

      <div className="split split--history">
        {/* Past plans ------------------------------------------------------ */}
        <Card as="section" elevation="flat" className="history">
          <h2 className="history__title">{t('plan.historyTitle')}</h2>
          {history.length === 0 ? (
            <p className="text-sm text-secondary">{t('plan.emptyTitle')}</p>
          ) : (
            <ul className="history__list">
              {history.map((plan) => (
                <li key={plan.id} className="history__row">
                  <button
                    type="button"
                    className={
                      current?.id === plan.id ? 'history__item is-active' : 'history__item'
                    }
                    aria-current={current?.id === plan.id ? 'true' : undefined}
                    onClick={() => void open(plan.id)}
                  >
                    <span className="history__item-title">{plan.topic}</span>
                    <span className="caption">
                      {plan.grade} · {formatDate(plan.createdAt, lang)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="history__delete"
                    aria-label={`${t('plan.delete')} — ${plan.topic}`}
                    title={t('plan.delete')}
                    onClick={() => void remove(plan.id)}
                  >
                    <Icon name="trash" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="stack stack-lg">
          {/* What to plan ------------------------------------------------- */}
          <Card as="section" elevation="raised">
            <form className="stack stack-md" onSubmit={build}>
              <Field label={t('plan.topicLabel')}>
                {(props) => (
                  <Input
                    {...props}
                    value={topic}
                    placeholder={t('plan.topicPlaceholder')}
                    onChange={(e) => setTopic(e.target.value)}
                    disabled={busy}
                  />
                )}
              </Field>

              <div className="plan__controls">
                <Field label={t('common.subject')}>
                  {(props) => (
                    <Select
                      {...props}
                      value={subject}
                      onChange={(e) => setSubject(e.target.value as SubjectId)}
                      options={SUBJECTS.map((item) => ({
                        value: item,
                        label: t(`subject.${item}`),
                      }))}
                    />
                  )}
                </Field>

                <Field label={t('common.grade')}>
                  {(props) => (
                    <Select
                      {...props}
                      value={String(grade)}
                      onChange={(e) => setGrade(Number(e.target.value))}
                      options={GRADES.map((g) => ({
                        value: String(g),
                        label: String(g),
                      }))}
                    />
                  )}
                </Field>

                <SegmentedControl
                  label={t('plan.durationLabel')}
                  value={String(duration)}
                  onChange={(value) => setDuration(Number(value))}
                  options={DURATIONS.map((d) => ({
                    value: String(d),
                    label: `${d} ${t('plan.minutes')}`,
                  }))}
                />

                <SegmentedControl
                  label={t('common.language')}
                  value={planLang}
                  onChange={(value) => setPlanLang(value as Lang)}
                  options={[
                    { value: 'kk', label: t('common.kazakh') },
                    { value: 'ru', label: t('common.russian') },
                  ]}
                />
              </div>

              <Field label={t('plan.sectionLabel')}>
                {(props) => (
                  <Input
                    {...props}
                    value={section}
                    placeholder={t('plan.sectionPlaceholder')}
                    onChange={(e) => setSection(e.target.value)}
                    disabled={busy}
                  />
                )}
              </Field>

              <Button type="submit" icon="sparkle" disabled={busy || !topic.trim()}>
                {busy ? t('plan.generating') : t('plan.generate')}
              </Button>
            </form>
          </Card>

          {busy ? (
            <Card as="section" elevation="raised" className="stack stack-sm">
              <h2 className="card__title">{t('plan.generating')}</h2>
              <p className="text-sm text-secondary">{t('plan.generatingBody')}</p>
            </Card>
          ) : null}

          {status === 'error' ? (
            <Alert tone="error" title={t('plan.errorTitle')}>
              {failure || t('plan.errorBody')}
            </Alert>
          ) : null}

          {status === 'idle' && !busy ? (
            <EmptyState
              icon="file"
              title={t('plan.emptyTitle')}
              body={t('plan.emptyBody')}
            />
          ) : null}

          {/* The document ------------------------------------------------- */}
          {status === 'ready' && current && doc ? (
            <Card as="section" elevation="raised" className="stack stack-lg">
              <div className="plan__head">
                <div className="stack stack-2xs">
                  <h2 className="card__title">{current.topic}</h2>
                  <div className="plan__meta">
                    <Badge>{t(`subject.${current.subject}`)}</Badge>
                    <Badge>{current.grade}</Badge>
                    <Badge tone={fits ? 'neutral' : 'warning'}>
                      {t('plan.minutesOf', {
                        planned: String(planned),
                        total: String(current.duration),
                      })}
                    </Badge>
                  </div>
                </div>
                <Button
                  icon={dirty ? 'check' : 'check'}
                  variant={dirty ? 'primary' : 'secondary'}
                  disabled={!dirty}
                  onClick={() => void save()}
                >
                  {dirty ? t('plan.save') : t('plan.saved')}
                </Button>
              </div>

              {/* Said once, near the top: these fields are the teacher's, and
                  a document that arrives with them filled in invites somebody
                  to submit a plausible lie about their own classroom. */}
              <Alert tone="info">{t('plan.teacherFills')}</Alert>

              {!fits ? (
                <Alert tone="warning">{t('plan.minutesMismatch')}</Alert>
              ) : null}

              <PlanField label={t('plan.section')} value={doc.section}
                         onChange={(v) => edit('section', v)} />

              <section className="stack stack-sm">
                <h3 className="plan__label">{t('plan.objectives')}</h3>
                <ul className="plan__objectives">
                  {doc.objectives.map((objective, index) => (
                    <li key={index} className="plan__objective">
                      <Badge tone={objective.code ? 'neutral' : 'warning'}>
                        {objective.code || t('plan.noCode')}
                      </Badge>
                      <span>{objective.text}</span>
                    </li>
                  ))}
                </ul>
                <p className="caption">{t('plan.codeHint')}</p>
              </section>

              <PlanField label={t('plan.lessonGoal')} value={doc.lesson_goal}
                         onChange={(v) => edit('lesson_goal', v)} multiline />

              {doc.success_criteria.length > 0 ? (
                <section className="stack stack-sm">
                  <h3 className="plan__label">{t('plan.successCriteria')}</h3>
                  <ul className="plan__criteria">
                    {doc.success_criteria.map((criterion, index) => (
                      <li key={index}>{criterion}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <div className="plan__pair">
                <PlanField label={t('plan.values')} value={doc.values}
                           onChange={(v) => edit('values', v)} multiline />
                <PlanField label={t('plan.crossCurricular')} value={doc.cross_curricular}
                           onChange={(v) => edit('cross_curricular', v)} multiline />
              </div>
              <PlanField label={t('plan.priorKnowledge')} value={doc.prior_knowledge}
                         onChange={(v) => edit('prior_knowledge', v)} multiline />

              {/* Сабақтың барысы: the table the whole document is built around */}
              <section className="stack stack-sm">
                <h3 className="plan__label">{t('plan.course')}</h3>
                {PHASES.map((phase) => {
                  const stages = doc.stages.filter((s) => s.phase === phase)
                  if (stages.length === 0) return null
                  return (
                    <div key={phase} className="stack stack-sm">
                      <h4 className="plan__phase">{t(`plan.phase.${phase}`)}</h4>
                      {stages.map((stage) => (
                        <article key={stage.id} className="plan__stage">
                          <header className="plan__stage-head">
                            <Input
                              className="plan__stage-title"
                              value={stage.title}
                              aria-label={t('plan.course')}
                              onChange={(e) => editStage(stage.id, 'title', e.target.value)}
                            />
                            <label className="plan__minutes">
                              <Input
                                type="number"
                                min={0}
                                max={120}
                                value={String(stage.minutes)}
                                aria-label={t('plan.minutes')}
                                onChange={(e) =>
                                  editStage(stage.id, 'minutes', Number(e.target.value) || 0)
                                }
                              />
                              <span className="caption">{t('plan.minutes')}</span>
                            </label>
                          </header>
                          <div className="plan__stage-grid">
                            <PlanField label={t('plan.colTeacher')} value={stage.teacher}
                                       onChange={(v) => editStage(stage.id, 'teacher', v)}
                                       multiline />
                            <PlanField label={t('plan.colStudent')} value={stage.student}
                                       onChange={(v) => editStage(stage.id, 'student', v)}
                                       multiline />
                            <PlanField label={t('plan.colAssessment')} value={stage.assessment}
                                       onChange={(v) => editStage(stage.id, 'assessment', v)}
                                       multiline />
                            <PlanField label={t('plan.colResources')} value={stage.resources}
                                       onChange={(v) => editStage(stage.id, 'resources', v)}
                                       multiline />
                          </div>
                        </article>
                      ))}
                    </div>
                  )
                })}
              </section>

              <PlanField label={t('plan.differentiation')} value={doc.differentiation}
                         onChange={(v) => edit('differentiation', v)} multiline />
              <PlanField label={t('plan.assessmentPlan')} value={doc.assessment_plan}
                         onChange={(v) => edit('assessment_plan', v)} multiline />
              <PlanField label={t('plan.healthSafety')} value={doc.health_safety}
                         onChange={(v) => edit('health_safety', v)} multiline />
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/** One labelled, editable field of the document.
 *
 *  Everything on this page is editable, because everything on it is going to
 *  be submitted under a teacher's name - so the wording has to be theirs. */
function PlanField({
  label,
  value,
  onChange,
  multiline = false,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  multiline?: boolean
}) {
  return (
    <Field label={label}>
      {(props) =>
        multiline ? (
          <Textarea
            {...props}
            rows={3}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        ) : (
          <Input {...props} value={value} onChange={(e) => onChange(e.target.value)} />
        )
      }
    </Field>
  )
}
