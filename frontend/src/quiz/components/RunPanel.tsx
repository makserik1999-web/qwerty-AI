/**
 * Where a run begins: who it is for, how long it lasts, how it behaves -
 * and the runs that already happened.
 */
import { Link } from 'react-router-dom'
import { Button, Icon } from '../../components/ui'
import { useI18n } from '../../lib/i18n'
import type { StringKey } from '../../lib/strings'
import { formatDateTime } from '../../lib/utils'
import type { Quiz, QuizSettings } from '../types'

const LIMITS = [0, 5, 10, 15, 20, 30]

const SWITCHES: Array<{ key: keyof QuizSettings; label: StringKey; hint: StringKey }> = [
  { key: 'shuffleQuestions', label: 'quiz.run.shuffleQuestions', hint: 'quiz.run.shuffleQuestionsHint' },
  { key: 'shuffleOptions', label: 'quiz.run.shuffleOptions', hint: 'quiz.run.shuffleOptionsHint' },
  { key: 'showResults', label: 'quiz.run.showResults', hint: 'quiz.run.showResultsHint' },
  { key: 'leaderboard', label: 'quiz.run.leaderboard', hint: 'quiz.run.leaderboardHint' },
  { key: 'lateJoin', label: 'quiz.run.lateJoin', hint: 'quiz.run.lateJoinHint' },
]

interface Props {
  quiz: Quiz
  classLabel: string
  onClassLabel: (value: string) => void
  onSettings: (patch: Partial<QuizSettings>) => void
  problemCount: number
  onShowProblem: () => void
  starting: boolean
  onStart: () => void
}

export function RunPanel({
  quiz,
  classLabel,
  onClassLabel,
  onSettings,
  problemCount,
  onShowProblem,
  starting,
  onStart,
}: Props) {
  const { t, lang } = useI18n()
  const settings = quiz.settings
  const runs = quiz.runs ?? []
  const labels = Array.from(new Set(runs.map((r) => r.classLabel).filter(Boolean)))
  const empty = quiz.questions.length === 0

  return (
    <aside className="qe-run">
      <section className="qe-run__card" aria-labelledby="run-title">
        <span className="qz-band qz-band--thin" />
        <div className="stack stack-sm">
          <h2 id="run-title" className="card__title">
            {t('quiz.run.title')}
          </h2>
          <p className="text-sm text-secondary">{t('quiz.run.subtitle')}</p>
        </div>

        <label className="field">
          <span className="field__label">{t('quiz.run.class')}</span>
          <input
            className="input"
            list="quiz-class-labels"
            value={classLabel}
            maxLength={40}
            placeholder={t('quiz.run.classPlaceholder')}
            onChange={(event) => onClassLabel(event.target.value)}
          />
          <datalist id="quiz-class-labels">
            {labels.map((label) => (
              <option key={label} value={label} />
            ))}
          </datalist>
        </label>

        <div className="field">
          <span className="field__label">{t('quiz.run.limit')}</span>
          <div className="qe-limits" role="radiogroup" aria-label={t('quiz.run.limit')}>
            {LIMITS.map((minutes) => (
              <button
                key={minutes}
                type="button"
                role="radio"
                aria-checked={settings.timeLimitMin === minutes}
                className="qe-limit"
                onClick={() => onSettings({ timeLimitMin: minutes })}
              >
                {minutes ? t('quiz.run.minutes', { n: minutes }) : t('quiz.run.noLimit')}
              </button>
            ))}
          </div>
        </div>

        <div className="qe-switches">
          {SWITCHES.map((item) => {
            const on = Boolean(settings[item.key])
            return (
              <div key={item.key} className="qe-switch" onClick={() => onSettings({ [item.key]: !on })}>
                <span>
                  {t(item.label)}
                  <span className="qe-switch__hint">{t(item.hint)}</span>
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={on}
                  aria-label={t(item.label)}
                  className="qz-toggle"
                  onClick={(event) => {
                    event.stopPropagation()
                    onSettings({ [item.key]: !on })
                  }}
                />
              </div>
            )
          })}
        </div>

        <Button
          variant="primary"
          icon="play"
          block
          className="qe-start"
          loading={starting}
          disabled={empty}
          onClick={onStart}
        >
          {t('quiz.run.start')}
        </Button>
        {problemCount ? (
          <button type="button" className="field__error" style={{ border: 0, background: 'none', cursor: 'pointer', padding: 0 }} onClick={onShowProblem}>
            <Icon name="alert" size={15} />
            {t('quiz.run.problems', { n: problemCount })}
          </button>
        ) : (
          <p className="caption" style={{ textAlign: 'center' }}>
            {empty ? t('quiz.run.empty') : t('quiz.run.startHint')}
          </p>
        )}
      </section>

      {runs.length ? (
        <section className="qe-run__card" aria-labelledby="runs-title">
          <h2 id="runs-title" className="card__title">
            {t('quiz.run.past')}
          </h2>
          <div className="qe-runs">
            {runs.slice(0, 8).map((run) => {
              const open = run.status !== 'ended'
              return (
                <Link
                  key={run.id}
                  to={open ? `/host/${run.id}` : `/app/quizzes/${quiz.id}/runs/${run.id}`}
                  className="qe-runs__item"
                >
                  <span className="qe-runs__label">
                    {open ? <span className="qe-live">{t('quiz.list.liveNow')}</span> : formatDateTime(run.createdAt, lang)}
                  </span>
                  <span className="text-secondary">
                    {run.averagePercent !== null ? `${run.averagePercent}%` : ''}
                  </span>
                  <span className="qe-runs__sub">
                    {[run.classLabel, t('quiz.list.players', { n: run.players })].filter(Boolean).join(' · ')}
                  </span>
                </Link>
              )
            })}
          </div>
        </section>
      ) : null}
    </aside>
  )
}
