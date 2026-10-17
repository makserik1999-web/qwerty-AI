import { useEffect, useState } from 'react'
import { VideoRating } from '../components/VideoRating'
import { VideoPlayer } from '../components/player/VideoPlayer'
import { Alert, Card, EmptyState, Select, Skeleton } from '../components/ui'
import { getShowcase, type ShowcaseVideo } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { GRADES, SUBJECTS } from '../lib/mockData'
import type { SubjectId } from '../lib/types'

/**
 * The showcase: topic videos the team has watched and put on display. Free
 * to watch for everyone - students, and teachers before or without a plan.
 * Nothing here was generated for the viewer, so nothing is charged.
 */
export function Showcase() {
  const { t } = useI18n()
  const [subject, setSubject] = useState('')
  const [grade, setGrade] = useState(0)
  const [items, setItems] = useState<ShowcaseVideo[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    setItems(null)
    setFailed(false)
    getShowcase(subject, grade)
      .then((found) => {
        if (active) setItems(found.items)
      })
      .catch(() => {
        if (active) setFailed(true)
      })
    return () => {
      active = false
    }
  }, [subject, grade])

  return (
    <div className="page">
      <header className="page__header">
        <div className="page__heading">
          <h1 className="page__title">{t('showcase.title')}</h1>
          <p className="page__subtitle">{t('showcase.subtitle')}</p>
        </div>
      </header>

      <div className="row row-wrap showcase__filters">
        <Select
          aria-label={t('showcase.allSubjects')}
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          options={[
            { value: '', label: t('showcase.allSubjects') },
            ...SUBJECTS.map((s) => ({ value: s, label: t(`subject.${s as SubjectId}`) })),
          ]}
        />
        <Select
          aria-label={t('showcase.allGrades')}
          value={String(grade)}
          onChange={(e) => setGrade(Number(e.target.value))}
          options={[
            { value: '0', label: t('showcase.allGrades') },
            ...GRADES.map((g) => ({ value: String(g), label: t('showcase.grade', { n: g }) })),
          ]}
        />
      </div>

      {failed ? <Alert tone="error">{t('showcase.loadFailed')}</Alert> : null}
      {!items && !failed ? (
        <div className="showcase__grid">
          {[0, 1, 2].map((i) => (
            <Card key={i} className="stack stack-sm">
              <Skeleton height="160px" radius="md" />
              <Skeleton width="60%" height="16px" />
            </Card>
          ))}
        </div>
      ) : null}
      {items && !items.length ? <EmptyState icon="video" title={t('showcase.empty')} /> : null}

      {items && items.length ? (
        <ul className="showcase__grid">
          {items.map((item) => (
            <li key={item.id}>
              <Card as="article" className="stack stack-sm showcase__card">
                <VideoPlayer src={item.video_url} title={item.title} />
                <h2 className="card__title">{item.title}</h2>
                <p className="caption">
                  {t(`subject.${item.subject as SubjectId}`)} · {t('showcase.grade', { n: item.grade })}
                  {item.duration ? ` · ${Math.round(item.duration)} с` : ''}
                </p>
                <VideoRating
                  videoId={item.id}
                  initial={{ up: item.rating_up, down: item.rating_down, mine: 0 }}
                />
              </Card>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
