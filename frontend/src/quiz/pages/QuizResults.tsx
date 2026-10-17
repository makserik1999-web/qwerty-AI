/**
 * What a run adds up to: the class, each question, each student - and first,
 * the misunderstandings the class shared.
 *
 * Those come first because they are the one thing a mark book cannot show.
 * When a third of the class picks the same wrong option, that is not thirty
 * separate mistakes but one idea to teach again, and the option's note says
 * which idea. From there it is one click to Explain with the question already
 * written - the product's other half, aimed at exactly what went wrong.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Alert, Button, Icon, Skeleton, Tabs, useToast } from '../../components/ui'
import { useI18n } from '../../lib/i18n'
import { cx, formatDateTime } from '../../lib/utils'
import { deleteRun, loadResults } from '../api'
import { QuestionText } from '../components/stage'
import { downloadCsv } from '../csv'
import { Glyph } from '../glyphs'
import type { ResultQuestion, Results } from '../types'
import '../quiz.css'

type Tab = 'questions' | 'students'

function seconds(value: number | null): string {
  if (value === null) return '—'
  const s = Math.round(value)
  return s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : `0:${String(s).padStart(2, '0')}`
}

export function QuizResults() {
  const { quizId = '', sessionId = '' } = useParams()
  const navigate = useNavigate()
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [results, setResults] = useState<Results | null>(null)
  const [failed, setFailed] = useState(false)
  const [tab, setTab] = useState<Tab>('questions')
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    loadResults(sessionId)
      .then(setResults)
      .catch(() => setFailed(true))
  }, [sessionId])

  const byId = useMemo(
    () => new Map((results?.questions ?? []).map((q) => [q.id, q])),
    [results],
  )

  if (failed) {
    return (
      <div className="page">
        <Alert tone="error" title={t('quiz.results.loadFailed')}>
          {t('quiz.list.loadFailedBody')}
        </Alert>
      </div>
    )
  }

  if (!results) {
    return (
      <div className="page">
        <Skeleton height="40px" width="40%" />
        <div className="qr-tiles">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} height="92px" />
          ))}
        </div>
        <Skeleton height="320px" />
      </div>
    )
  }

  const { session, summary } = results

  function explain(answer: string, question: string) {
    const prompt = t('quiz.results.explainPrompt', { answer, question: question.slice(0, 300) })
    navigate(`/app/explain?q=${encodeURIComponent(prompt)}`)
  }

  function explainQuestion(question: string) {
    const prompt = t('quiz.results.explainQuestionPrompt', { question: question.slice(0, 400) })
    navigate(`/app/explain?q=${encodeURIComponent(prompt)}`)
  }

  async function remove() {
    if (!window.confirm(t('quiz.results.deleteConfirm'))) return
    try {
      await deleteRun(sessionId)
      toast(t('quiz.results.deleted'))
      navigate(`/app/quizzes/${quizId}`)
    } catch {
      toast(t('quiz.list.actionFailed'), 'error')
    }
  }

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <nav className="qe-crumbs" aria-label={t('quiz.edit.crumbs')}>
            <Link to="/app/quizzes">{t('quiz.list.title')}</Link> /{' '}
            <Link to={`/app/quizzes/${quizId}`}>{session.title}</Link> / {t('quiz.results.crumb')}
          </nav>
          <h1 className="page__title">{session.title}</h1>
          <p className="page__subtitle">
            {[
              session.classLabel,
              formatDateTime(session.startsAt ?? session.createdAt, lang),
              t('quiz.results.code', { code: session.code }),
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <div className="row row--actions">
          <Button icon="download" onClick={() => downloadCsv(results, t)}>
            {t('quiz.results.csv')}
          </Button>
          <Button variant="quietDanger" icon="trash" onClick={() => void remove()}>
            {t('common.delete')}
          </Button>
        </div>
      </header>

      {session.status !== 'ended' ? (
        <Alert
          tone="info"
          title={t('quiz.results.stillOpen')}
          action={
            <Button onClick={() => navigate(`/host/${session.id}`)}>{t('quiz.results.toBoard')}</Button>
          }
        >
          {t('quiz.results.stillOpenBody')}
        </Alert>
      ) : null}

      <div className="qr-tiles">
        <div className="qr-tile">
          <span className="qr-tile__value">{summary.players}</span>
          <span className="qr-tile__label">{t('quiz.results.players')}</span>
        </div>
        <div className="qr-tile">
          <span className="qr-tile__value">
            {summary.averagePercent === null ? '—' : `${summary.averagePercent}%`}
          </span>
          <span className="qr-tile__label">{t('quiz.results.average')}</span>
        </div>
        <div className="qr-tile">
          <span className="qr-tile__value">{seconds(summary.medianDurationSec)}</span>
          <span className="qr-tile__label">{t('quiz.results.medianTime')}</span>
        </div>
        <div className="qr-tile">
          <span className="qr-tile__value">
            {summary.finished}/{summary.players}
          </span>
          <span className="qr-tile__label">{t('quiz.results.finished')}</span>
        </div>
      </div>

      {results.insights.length ? (
        <section className="stack stack-md" aria-labelledby="insights">
          <div className="stack stack-sm">
            <h2 id="insights" className="card__title">
              {t('quiz.results.insights')}
            </h2>
            <p className="text-sm text-secondary">{t('quiz.results.insightsBody')}</p>
          </div>
          <div className="qr-insights">
            {results.insights.map((insight, i) => (
              <article
                key={`${insight.questionId}-${insight.answer}`}
                className="qr-insight"
                style={{ '--i': i } as React.CSSProperties}
              >
                <span className="qr-insight__share">{Math.round(insight.share * 100)}%</span>
                <span className="qr-insight__answer">
                  {t('quiz.results.chose', { n: insight.count, answer: insight.answer })}
                </span>
                {insight.note ? <span className="qr-insight__note">{insight.note}</span> : null}
                <span className="qr-insight__question">
                  {t('quiz.results.inQuestion', { n: insight.questionIndex + 1 })}:{' '}
                  {insight.questionText.slice(0, 140)}
                </span>
                <div>
                  <Button size="sm" icon="video" onClick={() => explain(insight.answer, insight.questionText)}>
                    {t('quiz.results.explain')}
                  </Button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <Tabs
        label={t('quiz.results.crumb')}
        value={tab}
        onChange={setTab}
        items={[
          { value: 'questions', label: t('quiz.results.byQuestion') },
          { value: 'students', label: t('quiz.results.byStudent') },
        ]}
      >
        {tab === 'questions' ? (
          <div>
            {results.questions.map((question) => (
              <QuestionRow
                key={question.id}
                question={question}
                open={open === question.id}
                hardest={summary.hardest === question.id && results.questions.length > 1}
                onToggle={() => setOpen((v) => (v === question.id ? null : question.id))}
                onExplain={explainQuestion}
              />
            ))}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="qr-people">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>{t('quiz.results.name')}</th>
                  <th className="num">{t('quiz.results.score')}</th>
                  <th>{t('quiz.results.correct')}</th>
                  <th className="num">{t('quiz.results.time')}</th>
                  <th>{t('quiz.results.answers')}</th>
                </tr>
              </thead>
              <tbody>
                {results.players.map((person, i) => (
                  <tr key={person.id} style={{ '--i': i } as React.CSSProperties}>
                    <td className="num">{person.rank}</td>
                    <td>{person.name}</td>
                    <td className="num">{person.score}</td>
                    <td>
                      <span className="qr-bar" aria-hidden="true">
                        <span style={{ width: `${person.percent}%` }} />
                      </span>
                      {person.correct}/{person.total} · {person.percent}%
                    </td>
                    <td className="num">{seconds(person.durationSec)}</td>
                    <td>
                      <span className="qr-dots">
                        {person.answers.map((answer, n) => (
                          <span
                            key={answer.questionId}
                            className={cx(
                              'qr-dot',
                              answer.correct === true && 'is-right',
                              answer.correct === false && 'is-wrong',
                            )}
                            title={`${n + 1}. ${byId.get(answer.questionId)?.text.slice(0, 60) ?? ''} — ${
                              answer.skipped ? t('quiz.results.skipped') : answer.value || '—'
                            }`}
                          />
                        ))}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {results.players.length === 0 ? (
              <p className="text-secondary" style={{ padding: 'var(--space-lg) 0' }}>
                {t('quiz.results.nobody')}
              </p>
            ) : null}
          </div>
        )}
      </Tabs>
    </div>
  )
}

function QuestionRow({
  question,
  open,
  hardest,
  onToggle,
  onExplain,
}: {
  question: ResultQuestion
  open: boolean
  hardest: boolean
  onToggle: () => void
  onExplain: (question: string) => void
}) {
  const { t } = useI18n()
  const rate = question.rate
  const total = Math.max(1, question.answered)

  return (
    <div className="qr-q" style={{ cursor: 'pointer' }} onClick={onToggle}>
      <span className="qe-number">{question.index + 1}</span>
      <div className="qr-q__text">
        <QuestionText text={question.text} />
      </div>
      <div
        className="qr-split"
        aria-label={t('quiz.results.split')}
        title={hardest ? t('quiz.results.hardest') : undefined}
      >
        {question.type === 'choice'
          ? (question.options ?? []).map((option, i) =>
              option.count ? (
                <span
                  key={option.id}
                  className={cx('qr-split__part', `qz-tones-${i}`, option.correct && 'is-correct')}
                  style={{ flexGrow: option.count, '--i': i } as React.CSSProperties}
                />
              ) : null,
            )
          : [
              <span
                key="right"
                className="qr-split__part"
                style={{ flexGrow: question.correct, background: 'var(--success)' } as React.CSSProperties}
              />,
              <span
                key="wrong"
                className="qr-split__part"
                style={{ flexGrow: question.answered - question.correct, background: 'var(--error)', '--i': 1 } as React.CSSProperties}
              />,
            ]}
      </div>
      <span
        className={cx('qr-rate', rate !== null && rate < 0.5 && 'is-low', rate !== null && rate >= 0.8 && 'is-high')}
      >
        {rate === null ? '—' : `${Math.round(rate * 100)}%`}
      </span>

      {open ? (
        <div className="qr-detail" onClick={(event) => event.stopPropagation()}>
          {question.type === 'choice' ? (
            (question.options ?? []).map((option, i) => (
              <div key={option.id} className={cx('qr-option', option.correct && 'is-correct')}>
                <span className={cx('qr-option__mark', `qz-tones-${i}`)}>
                  <Glyph index={i} size={14} />
                </span>
                <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                  <span>{option.text}</span>
                  {!option.correct && option.note ? (
                    <span className="caption">{option.note}</span>
                  ) : null}
                </span>
                <span className="qr-option__count">
                  {Math.round((option.count / total) * 100)}%
                </span>
              </div>
            ))
          ) : (
            <>
              <div className="qr-option is-correct">
                <Icon name="check" size={16} />
                <span>
                  {question.answer} {question.unit}
                </span>
                <span className="qr-option__count">{question.correct}</span>
              </div>
              {(question.wrongAnswers ?? []).map((wrong) => (
                <div key={wrong.text} className="qr-option">
                  <Icon name="close" size={16} />
                  <span>{wrong.text}</span>
                  <span className="qr-option__count">{wrong.count}</span>
                </div>
              ))}
            </>
          )}
          {question.explanation ? (
            <p className="text-sm text-secondary" style={{ gridColumn: '1 / -1' }}>
              {question.explanation}
            </p>
          ) : null}
          {rate !== null && rate < 0.6 ? (
            <div style={{ gridColumn: '1 / -1' }}>
              <Button size="sm" icon="video" onClick={() => onExplain(question.text)}>
                {t('quiz.results.explainQuestion')}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
