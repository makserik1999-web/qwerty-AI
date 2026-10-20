/**
 * A teacher's quizzes, and the way to a new one.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Button, Menu, Skeleton, useToast } from '../../components/ui'
import { useI18n } from '../../lib/i18n'
import { formatDate } from '../../lib/utils'
import { copyQuiz, deleteQuiz, listQuizzes } from '../api'
import { NewQuizModal } from '../components/NewQuizModal'
import { Glyph } from '../glyphs'
import type { QuizSummary } from '../types'
import '../quiz.css'

export function QuizList() {
  const { t, lang } = useI18n()
  const navigate = useNavigate()
  const { toast } = useToast()
  const [items, setItems] = useState<QuizSummary[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    listQuizzes()
      .then(setItems)
      .catch(() => setFailed(true))
  }, [])

  async function onCopy(item: QuizSummary) {
    try {
      const copy = await copyQuiz(item.id)
      toast(t('quiz.list.copied'))
      navigate(`/app/quizzes/${copy.id}`)
    } catch {
      toast(t('quiz.list.actionFailed'), 'error')
    }
  }

  async function onDelete(item: QuizSummary) {
    if (!window.confirm(t('quiz.list.deleteConfirm', { title: item.title }))) return
    try {
      await deleteQuiz(item.id)
      setItems((list) => list?.filter((q) => q.id !== item.id) ?? list)
      toast(t('quiz.list.deleted'))
    } catch {
      toast(t('quiz.list.actionFailed'), 'error')
    }
  }

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('quiz.list.title')}</h1>
          <p className="page__subtitle">{t('quiz.list.subtitle')}</p>
        </div>
        {items && items.length > 0 ? (
          <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>
            {t('quiz.list.new')}
          </Button>
        ) : null}
      </header>

      {failed ? (
        <Alert tone="error" title={t('quiz.list.loadFailed')}>
          {t('quiz.list.loadFailedBody')}
        </Alert>
      ) : null}

      {items === null && !failed ? (
        <div className="ql-grid">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height="188px" />
          ))}
        </div>
      ) : null}

      {items && items.length === 0 ? (
        <section className="ql-hero">
          <div className="stack stack-md">
            <h2>{t('quiz.list.emptyTitle')}</h2>
            <p className="text-secondary measure">{t('quiz.list.emptyBody')}</p>
            <div className="row row-wrap">
              <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>
                {t('quiz.list.new')}
              </Button>
              <Link to="/join" className="text-sm">
                {t('quiz.list.studentLink')}
              </Link>
            </div>
          </div>
          <div className="ql-hero__marks" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <span key={i} className={`qz-tones-${i}`} style={{ '--i': i } as React.CSSProperties}>
                <Glyph index={i} size={34} />
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {items && items.length > 0 ? (
        <div className="ql-grid">
          <button type="button" className="ql-new" onClick={() => setCreating(true)}>
            <Glyph index={2} size={28} />
            {t('quiz.list.new')}
          </button>
          {items.map((item, index) => (
            <article key={item.id} className="ql-card" style={{ '--i': index } as React.CSSProperties}>
              <span className="qz-band" />
              <span className="ql-card__meta">
                {item.subject !== 'other' ? t(`subject.${item.subject}`) : t('quiz.subject.other')}
                {item.grade ? ` · ${t('quiz.list.grade', { n: item.grade })}` : ''}
              </span>
              <Link to={`/app/quizzes/${item.id}`} className="ql-card__title ql-card__link">
                {item.title}
              </Link>
              <span className="ql-card__meta">
                {t('quiz.list.questions', { n: item.questionCount })}
                {!item.ready && item.questionCount > 0 ? ` · ${t('quiz.list.notReady')}` : ''}
              </span>
              <span className="ql-card__foot">
                {item.lastRun ? (
                  <>
                    {item.lastRun.status !== 'ended' ? (
                      <span className="qe-live">{t('quiz.list.liveNow')}</span>
                    ) : (
                      formatDate(item.lastRun.createdAt, lang)
                    )}
                    <span>·</span>
                    <span>{t('quiz.list.players', { n: item.lastRun.players })}</span>
                    {item.lastRun.averagePercent !== null ? (
                      <>
                        <span>·</span>
                        <span>{item.lastRun.averagePercent}%</span>
                      </>
                    ) : null}
                  </>
                ) : (
                  t('quiz.list.neverRun')
                )}
              </span>
              <div className="ql-card__menu">
                <Menu
                  label={t('common.actions')}
                  items={[
                    { key: 'copy', label: t('quiz.list.copy'), icon: 'copy', onSelect: () => void onCopy(item) },
                    {
                      key: 'delete',
                      label: t('common.delete'),
                      icon: 'trash',
                      danger: true,
                      onSelect: () => void onDelete(item),
                    },
                  ]}
                />
              </div>
            </article>
          ))}
        </div>
      ) : null}

      <NewQuizModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(quiz) => navigate(`/app/quizzes/${quiz.id}`)}
      />
    </div>
  )
}
