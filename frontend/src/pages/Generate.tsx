import { useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  IconButton,
  Input,
  SegmentedControl,
  Select,
  Skeleton,
  SkeletonText,
  Stepper,
  Table,
  Tabs,
  Textarea,
  useToast,
} from '../components/ui'
import { useI18n } from '../lib/i18n'
import {
  exportDocument,
  generateAssessment,
  regenerateQuestion,
  type GenerateAssessmentInput,
} from '../lib/mockApi'
import { GRADES, SUBJECTS } from '../lib/mockData'
import { useStore } from '../lib/store'
import type {
  Assessment,
  AssessmentType,
  Difficulty,
  Lang,
  SubjectId,
} from '../lib/types'
import { formatDate } from '../lib/utils'

type Status = 'idle' | 'generating' | 'ready' | 'error'
type PreviewTab = 'document' | 'key'

export function Generate() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const { charge } = useStore()

  const [subject, setSubject] = useState<SubjectId>('math')
  const [grade, setGrade] = useState(8)
  const [topic, setTopic] = useState('')
  const [type, setType] = useState<AssessmentType>('sor')
  const [count, setCount] = useState(5)
  const [difficulty, setDifficulty] = useState<Difficulty>('medium')
  const [docLang, setDocLang] = useState<Lang>('kk')
  const [demoFail, setDemoFail] = useState(false)

  const [status, setStatus] = useState<Status>('idle')
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [topicError, setTopicError] = useState<string | undefined>()
  const [busyQuestion, setBusyQuestion] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null)
  const [tab, setTab] = useState<PreviewTab>('document')

  function currentInput(): GenerateAssessmentInput {
    return {
      subject,
      grade,
      topic: topic.trim(),
      type,
      difficulty,
      lang: docLang,
      count,
      shouldFail: demoFail,
    }
  }

  async function onGenerate(event: React.FormEvent) {
    event.preventDefault()
    if (!topic.trim()) {
      setTopicError(t('generate.topicRequired'))
      return
    }
    setTopicError(undefined)
    setStatus('generating')
    try {
      const result = await generateAssessment(currentInput())
      setAssessment(result)
      setStatus('ready')
      charge('assessment', 1, `${t(`subject.${subject}`)} · ${grade}`)
      toast(t('generate.saved'))
    } catch {
      setStatus('error')
    }
  }

  async function onRegenerateQuestion(questionId: string, index: number) {
    if (!assessment) return
    setBusyQuestion(questionId)
    const replacement = await regenerateQuestion(currentInput(), index)
    setAssessment({
      ...assessment,
      questions: assessment.questions.map((question) =>
        question.id === questionId ? { ...replacement, id: question.id } : question,
      ),
    })
    setBusyQuestion(null)
    toast(t('generate.questionUpdated'))
  }

  function saveEdit(questionId: string) {
    if (!assessment) return
    setAssessment({
      ...assessment,
      questions: assessment.questions.map((question) =>
        question.id === questionId ? { ...question, text: editValue } : question,
      ),
    })
    setEditingId(null)
    toast(t('generate.questionUpdated'))
  }

  async function onExport(format: 'pdf' | 'docx') {
    setExporting(format)
    await exportDocument(format)
    setExporting(null)
    toast(t('generate.exported', { format: format.toUpperCase() }))
  }

  const totalMarks =
    assessment?.questions.reduce((sum, question) => sum + question.marks, 0) ?? 0

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('generate.title')}</h1>
          <p className="page__subtitle">{t('generate.subtitle')}</p>
        </div>
      </header>

      <div className="split split--form">
        {/* Form ------------------------------------------------------------- */}
        <Card as="section" elevation="raised">
          <h2 className="card__title">{t('generate.form')}</h2>
          <form className="stack stack-md generate__form" onSubmit={onGenerate}>
            <Field label={t('common.subject')}>
              {(props) => (
                <Select
                  {...props}
                  value={subject}
                  onChange={(event) => setSubject(event.target.value as SubjectId)}
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
                  onChange={(event) => setGrade(Number(event.target.value))}
                  options={GRADES.map((item) => ({
                    value: String(item),
                    label: String(item),
                  }))}
                />
              )}
            </Field>

            <Field label={t('common.topic')} error={topicError}>
              {(props) => (
                <Input
                  {...props}
                  value={topic}
                  placeholder={t('generate.topicPlaceholder')}
                  onChange={(event) => setTopic(event.target.value)}
                />
              )}
            </Field>

            <Field label={t('generate.type')}>
              {(props) => (
                <Select
                  {...props}
                  value={type}
                  onChange={(event) => setType(event.target.value as AssessmentType)}
                  options={[
                    { value: 'sor', label: t('generate.type.sor') },
                    { value: 'soch', label: t('generate.type.soch') },
                    { value: 'quiz', label: t('generate.type.quiz') },
                  ]}
                />
              )}
            </Field>

            <div className="field">
              <span className="field__label">{t('generate.count')}</span>
              <Stepper
                value={count}
                min={3}
                max={15}
                onChange={setCount}
                label={t('generate.count')}
                decreaseLabel="−1"
                increaseLabel="+1"
              />
            </div>

            <div className="field">
              <span className="field__label">{t('generate.difficulty')}</span>
              <SegmentedControl
                label={t('generate.difficulty')}
                value={difficulty}
                onChange={setDifficulty}
                options={[
                  { value: 'easy', label: t('generate.difficulty.easy') },
                  { value: 'medium', label: t('generate.difficulty.medium') },
                  { value: 'hard', label: t('generate.difficulty.hard') },
                ]}
              />
            </div>

            <div className="field">
              <span className="field__label">{t('common.language')}</span>
              <SegmentedControl
                label={t('common.language')}
                value={docLang}
                onChange={setDocLang}
                options={[
                  { value: 'kk', label: t('common.kazakh') },
                  { value: 'ru', label: t('common.russian') },
                ]}
              />
            </div>

            <Button
              type="submit"
              variant="primary"
              icon="sparkle"
              block
              loading={status === 'generating'}
            >
              {assessment ? t('generate.regenerate') : t('generate.submit')}
            </Button>

            <label className="demo-bar demo-bar--inline">
              <input
                type="checkbox"
                checked={demoFail}
                onChange={(event) => setDemoFail(event.target.checked)}
              />
              {t('generate.demoFail')}
            </label>
          </form>
        </Card>

        {/* Preview ---------------------------------------------------------- */}
        <section
          className="stack stack-md"
          aria-live="polite"
          aria-busy={status === 'generating'}
        >
          <div className="row row-between row-wrap">
            <h2 className="card__title">{t('generate.preview')}</h2>
            <div className="row row--actions">
              <Button
                icon="download"
                disabled={!assessment}
                loading={exporting === 'pdf'}
                onClick={() => void onExport('pdf')}
              >
                {t('generate.exportPdf')}
              </Button>
              <Button
                icon="download"
                disabled={!assessment}
                loading={exporting === 'docx'}
                onClick={() => void onExport('docx')}
              >
                {t('generate.exportDocx')}
              </Button>
            </div>
          </div>

          {status === 'idle' ? (
            <EmptyState
              icon="file"
              title={t('generate.previewEmptyTitle')}
              body={t('generate.previewEmptyBody')}
            />
          ) : null}

          {status === 'error' ? (
            <Alert
              tone="error"
              title={t('generate.errorTitle')}
              action={
                <Button
                  icon="refresh"
                  onClick={() => {
                    setDemoFail(false)
                    setStatus('idle')
                  }}
                >
                  {t('common.retry')}
                </Button>
              }
            >
              {t('generate.errorBody')}
            </Alert>
          ) : null}

          {status === 'generating' ? (
            <Card elevation="flat" className="stack stack-md">
              <Skeleton width="50%" height="24px" />
              <Skeleton width="80%" height="14px" />
              {Array.from({ length: count }, (_, index) => (
                <SkeletonText key={index} lines={2} />
              ))}
            </Card>
          ) : null}

          {status === 'ready' && assessment ? (
            <Tabs
              label={t('generate.preview')}
              value={tab}
              onChange={setTab}
              items={[
                { value: 'document', label: t('generate.tab.document') },
                { value: 'key', label: t('generate.tab.key') },
              ]}
            >
              {tab === 'key' ? (
                <Card elevation="raised" className="document">
                  <header className="document__header">
                    <h3 className="document__title">{t('generate.tab.key')}</h3>
                    <Badge tone="accent">
                      {t('generate.totalMarks', { n: totalMarks })}
                    </Badge>
                  </header>
                  <p className="text-sm text-secondary">{t('generate.criteria.note')}</p>
                  <Table caption={t('generate.tab.key')}>
                    <thead>
                      <tr>
                        <th scope="col">{t('generate.criteria.question')}</th>
                        <th scope="col">{t('generate.criteria.level')}</th>
                        <th scope="col" className="num">
                          {t('generate.criteria.marks')}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {assessment.questions.flatMap((question, index) => {
                        const levels = [
                          { key: 'full', marks: question.marks },
                          {
                            key: 'partial',
                            marks: Math.max(1, Math.round(question.marks / 2)),
                          },
                          { key: 'start', marks: 1 },
                        ] as const
                        return levels.map((level, levelIndex) => (
                          <tr key={`${question.id}-${level.key}`}>
                            {levelIndex === 0 ? (
                              <th scope="row" rowSpan={3} className="table__rowhead">
                                {index + 1}
                              </th>
                            ) : null}
                            <td>{t(`generate.criteria.${level.key}`)}</td>
                            <td className="num">{level.marks}</td>
                          </tr>
                        ))
                      })}
                    </tbody>
                  </Table>
                </Card>
              ) : (
                <Card elevation="raised" className="document">
                  <header className="document__header">
                    <div className="stack stack-sm">
                      <h3 className="document__title">
                        {t(`generate.type.${assessment.type}`)} ·{' '}
                        {t(`subject.${assessment.subject}`)}
                      </h3>
                      <p className="text-sm text-secondary">
                        {assessment.grade} {t('common.grade').toLowerCase()} ·{' '}
                        {assessment.topic} · {formatDate(assessment.createdAt, lang)}
                      </p>
                    </div>
                    <Badge tone="accent">
                      {t('generate.totalMarks', { n: totalMarks })}
                    </Badge>
                  </header>

                  <dl className="document__fields">
                    <div>
                      <dt>{t('generate.docHeaderName')}</dt>
                      <dd />
                    </div>
                    <div>
                      <dt>{t('generate.docHeaderClass')}</dt>
                      <dd />
                    </div>
                    <div>
                      <dt>{t('generate.docHeaderDate')}</dt>
                      <dd />
                    </div>
                  </dl>

                  <section className="document__instructions">
                    <h4>{t('generate.instructions')}</h4>
                    <p className="text-sm text-secondary">
                      {t('generate.instructionsBody')}
                    </p>
                  </section>

                  <ol className="document__questions">
                    {assessment.questions.map((question, index) => (
                      <li key={question.id} className="document__question">
                        <div className="document__question-head">
                          <span className="document__question-number">{index + 1}.</span>
                          <Badge tone="neutral">
                            {t('generate.marks', { n: question.marks })}
                          </Badge>
                          <span className="grow" />
                          <IconButton
                            icon="pencil"
                            label={t('generate.editQuestion', { n: index + 1 })}
                            onClick={() => {
                              setEditingId(question.id)
                              setEditValue(question.text)
                            }}
                          />
                          <IconButton
                            icon="refresh"
                            label={t('generate.regenerateQuestion', {
                              n: index + 1,
                            })}
                            disabled={busyQuestion === question.id}
                            onClick={() => void onRegenerateQuestion(question.id, index)}
                          />
                        </div>

                        {busyQuestion === question.id ? (
                          <Skeleton height="14px" />
                        ) : editingId === question.id ? (
                          <div className="stack stack-sm">
                            <label
                              className="visually-hidden"
                              htmlFor={`edit-${question.id}`}
                            >
                              {t('generate.editQuestion', { n: index + 1 })}
                            </label>
                            <Textarea
                              id={`edit-${question.id}`}
                              value={editValue}
                              rows={3}
                              onChange={(event) => setEditValue(event.target.value)}
                            />
                            <div className="row row--actions">
                              <Button size="sm" onClick={() => setEditingId(null)}>
                                {t('common.cancel')}
                              </Button>
                              <Button
                                size="sm"
                                variant="primary"
                                onClick={() => saveEdit(question.id)}
                              >
                                {t('common.save')}
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <p>{question.text}</p>
                        )}
                      </li>
                    ))}
                  </ol>
                </Card>
              )}
            </Tabs>
          ) : null}
        </section>
      </div>
    </div>
  )
}
