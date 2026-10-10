/**
 * The projector: what the class sees while a quiz runs.
 *
 * Three acts. The lobby - the code on a departure board, a QR code, names
 * dropping in as students join. The run - a lane per student, their token
 * travelling as they answer: progress only, never who got what wrong, because
 * this is on a wall the whole room can read. And the end - a podium, if the
 * teacher wants one, and the way to the full results.
 *
 * Opened full-screen, outside the app's chrome, by the teacher who owns it.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Icon } from '../../components/ui'
import { useI18n } from '../../lib/i18n'
import { cx } from '../../lib/utils'
import { QuizError, endRun, loadRun, removePlayer, startRun } from '../api'
import { CodeBoard, Countdown, CountUp, QrCode, initials, toneOf } from '../components/stage'
import { Glyph } from '../glyphs'
import { useQuizSocket, useServerClock, useTicker } from '../live'
import type { HostEvent, HostPlayer, HostState, QuestionTally } from '../types'
import '../quiz.css'

const ROW = 46

function upsert(players: HostPlayer[], player: HostPlayer): HostPlayer[] {
  const at = players.findIndex((p) => p.id === player.id)
  if (at === -1) return [...players, player]
  const next = [...players]
  next[at] = player
  return next
}

function tallyAnswer(
  tallies: QuestionTally[],
  questionId: string,
  optionId: string | null,
  correct: boolean,
): QuestionTally[] {
  return tallies.map((q) =>
    q.id !== questionId
      ? q
      : {
          ...q,
          answered: q.answered + 1,
          correct: q.correct + (correct ? 1 : 0),
          options: q.options?.map((o) => (o.id === optionId ? { ...o, count: o.count + 1 } : o)),
        },
  )
}

function reduce(state: HostState | null, event: HostEvent): HostState | null {
  if (event.type === 'snapshot') return event.state
  if (!state) return state
  switch (event.type) {
    case 'joined':
      return { ...state, players: upsert(state.players, event.player) }
    case 'left':
      return { ...state, players: state.players.filter((p) => p.id !== event.playerId) }
    case 'answer':
      return {
        ...state,
        players: upsert(state.players, event.player),
        questions: tallyAnswer(state.questions, event.questionId, event.optionId, event.correct),
      }
    case 'finished':
      return { ...state, players: upsert(state.players, event.player) }
    case 'status':
      return {
        ...state,
        status: event.status,
        startsAt: event.startsAt ?? state.startsAt,
        endedAt: event.endedAt ?? state.endedAt,
      }
    default:
      return state
  }
}

/** Best first: score, then further along, then who joined first. */
function standings(players: HostPlayer[]): HostPlayer[] {
  return [...players].sort(
    (a, b) =>
      b.score - a.score || b.answered - a.answered || Date.parse(a.joinedAt) - Date.parse(b.joinedAt),
  )
}

export function QuizHost() {
  const { sessionId = '' } = useParams()
  const navigate = useNavigate()
  const { t } = useI18n()
  const { sync, now } = useServerClock()
  const [state, setState] = useState<HostState | null>(null)
  const [failure, setFailure] = useState('')
  const [hideNames, setHideNames] = useState(false)
  const [teacherView, setTeacherView] = useState(false)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [pendingRemove, setPendingRemove] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const apply = useCallback(
    (next: HostState) => {
      sync(next.serverNow)
      setState(next)
    },
    [sync],
  )

  useEffect(() => {
    loadRun(sessionId)
      .then(apply)
      .catch((error) => {
        setFailure(error instanceof QuizError && error.status === 404 ? t('quiz.host.notFound') : t('quiz.host.loadFailed'))
      })
  }, [sessionId, apply, t])

  const { connected } = useQuizSocket<HostEvent>({
    path: `/ws/quiz/host/${sessionId}`,
    enabled: Boolean(sessionId),
    onEvent: (event) => {
      if (event.type === 'snapshot') sync(event.state.serverNow)
      if (event.type === 'status') sync(event.serverNow)
      setState((current) => reduce(current, event))
    },
  })

  useEffect(() => {
    if (!confirmEnd) return
    const id = window.setTimeout(() => setConfirmEnd(false), 3500)
    return () => window.clearTimeout(id)
  }, [confirmEnd])

  const startsAt = state?.startsAt ? Date.parse(state.startsAt) : null
  const counting = state?.status === 'running' && startsAt !== null && startsAt > now()
  useTicker(counting, 100)

  const label = useCallback(
    (player: HostPlayer, index: number) => (hideNames ? t('quiz.host.student', { n: index + 1 }) : player.name),
    [hideNames, t],
  )

  async function act(run: () => Promise<HostState>) {
    setBusy(true)
    try {
      apply(await run())
    } catch (error) {
      setFailure(error instanceof QuizError && error.detail ? error.detail : t('quiz.host.actionFailed'))
    } finally {
      setBusy(false)
    }
  }

  async function remove(player: HostPlayer) {
    if (pendingRemove !== player.id) {
      setPendingRemove(player.id)
      return
    }
    setPendingRemove(null)
    try {
      await removePlayer(sessionId, player.id)
      setState((current) => (current ? { ...current, players: current.players.filter((p) => p.id !== player.id) } : current))
    } catch {
      setFailure(t('quiz.host.actionFailed'))
    }
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void document.documentElement.requestFullscreen?.().catch(() => undefined)
  }

  if (!state) {
    return (
      <div className="stage host">
        <div className="qz-band" />
        <div className="stage__center">
          {failure ? (
            <>
              <h1 className="stage__headline">{failure}</h1>
              <Link className="stage-btn stage-btn--quiet" to="/app/quizzes">
                {t('quiz.host.backToQuizzes')}
              </Link>
            </>
          ) : (
            <div className="qz-wait">
              <span className="qz-wait__ring" />
              <Glyph index={0} size={64} className="qz-wait__glyph" />
            </div>
          )}
        </div>
      </div>
    )
  }

  const joinHost = window.location.host
  const joinUrl = `${window.location.origin}/join/${state.code}`

  return (
    <div className="stage host">
      <div className="qz-band" />
      <header className="stage__bar">
        <Link to={`/app/quizzes/${state.quizId}`} className="host__toggle" aria-label={t('quiz.host.close')}>
          <Icon name="chevronLeft" size={18} />
        </Link>
        <span className="stage__title">
          {state.title}
          {state.classLabel ? ` · ${state.classLabel}` : ''}
        </span>
        <span className="grow" />
        {!connected ? (
          <span className="stage-pill stage-pill--warn">
            <Icon name="refresh" size={14} />
            {t('quiz.host.reconnecting')}
          </span>
        ) : null}
        {state.status === 'running' ? (
          <span className="stage-pill">
            {t('quiz.host.codeSmall')} <strong>{state.code}</strong>
          </span>
        ) : null}
        <button type="button" className="host__toggle" aria-pressed={hideNames} onClick={() => setHideNames((v) => !v)}>
          <Icon name={hideNames ? 'eyeOff' : 'eye'} size={16} />
          {t('quiz.host.hideNames')}
        </button>
        <button type="button" className="host__toggle" onClick={toggleFullscreen} aria-label={t('quiz.host.fullscreen')}>
          <Icon name="maximize" size={16} />
        </button>
      </header>

      {failure ? (
        <div className="stage-pill stage-pill--warn" role="alert" style={{ alignSelf: 'center' }}>
          {failure}
        </div>
      ) : null}

      {state.status === 'lobby' ? (
        <>
          <section className="host__body host__lobby">
            <div className="host__join">
              <div className="host__url">
                {t('quiz.host.goTo')} <strong>{joinHost}/join</strong>
              </div>
              <CodeBoard code={state.code} className="host__code" />
              <div className="host__qr">
                <div className="host__qr-card">
                  <QrCode text={joinUrl} label={t('quiz.host.qrLabel')} />
                </div>
                <p className="stage__lead">{t('quiz.host.qrHint')}</p>
              </div>
            </div>
            <div className="host__people">
              <div className="host__count">
                <span className="host__count-number">
                  <CountUp value={state.players.length} duration={500} />
                </span>
                <span className="stage__lead">{t('quiz.host.joinedLabel', { n: state.players.length })}</span>
              </div>
              {state.players.length === 0 ? (
                <p className="host__empty">{t('quiz.host.waitingFirst')}</p>
              ) : (
                <div className="host__chips" aria-live="polite">
                  {state.players.map((player, index) => (
                    <button
                      key={player.id}
                      type="button"
                      className={cx('host__chip', `qz-tones-${toneOf(player.name)}`)}
                      title={t('quiz.host.removeHint')}
                      onClick={() => void remove(player)}
                    >
                      <span className="qz-avatar">
                        {pendingRemove === player.id ? <Icon name="close" size={16} /> : initials(player.name)}
                      </span>
                      {pendingRemove === player.id ? t('quiz.host.removeConfirm') : label(player, index)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </section>
          <footer className="host__foot">
            <button
              type="button"
              className="stage-btn stage-btn--go"
              disabled={busy || state.players.length === 0}
              onClick={() => void act(() => startRun(sessionId))}
            >
              <Icon name="play" size={20} />
              {t('quiz.host.start')}
            </button>
            <span className="stage__lead">
              {state.settings.timeLimitMin
                ? t('quiz.host.limitNote', { n: state.settings.timeLimitMin })
                : t('quiz.host.noLimitNote')}
            </span>
            <span className="grow" />
            <button type="button" className="stage-link" onClick={() => void act(() => endRun(sessionId))}>
              {t('quiz.host.cancel')}
            </button>
          </footer>
        </>
      ) : state.status === 'running' ? (
        <>
          <Running
            state={state}
            label={label}
            hideNames={hideNames}
            teacherView={teacherView}
          />
          <footer className="host__foot">
            <button
              type="button"
              className={cx('stage-btn', confirmEnd ? 'stage-btn--go' : 'stage-btn--quiet')}
              disabled={busy}
              onClick={() => {
                if (!confirmEnd) setConfirmEnd(true)
                else void act(() => endRun(sessionId))
              }}
            >
              {confirmEnd ? t('quiz.host.endConfirm') : t('quiz.host.end')}
            </button>
            <button
              type="button"
              className="host__toggle"
              aria-pressed={teacherView}
              onClick={() => setTeacherView((v) => !v)}
            >
              <Icon name="info" size={16} />
              {t('quiz.host.teacherView')}
            </button>
            {teacherView ? <span className="stage__lead">{t('quiz.host.teacherViewWarn')}</span> : null}
          </footer>
          {counting && startsAt ? (
            <div className="host__overlay">
              <div className="stage__center">
                <p className="stage__lead">{t('quiz.host.starting')}</p>
                <Countdown remainingMs={startsAt - now()} totalMs={4000} />
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <Ended
          state={state}
          label={label}
          hideNames={hideNames}
          onResults={() => navigate(`/app/quizzes/${state.quizId}/runs/${state.id}`)}
        />
      )}
    </div>
  )
}

/* ----------------------------------------------------------- running -- */

function Running({
  state,
  label,
  hideNames,
  teacherView,
}: {
  state: HostState
  label: (player: HostPlayer, index: number) => string
  hideNames: boolean
  teacherView: boolean
}) {
  const { t } = useI18n()
  const total = state.questionCount
  const finished = state.players.filter((p) => p.status === 'finished').length
  // Everyone still in it - a student who has not answered yet is answering
  // too, and their stored status only changes when they first do.
  const answering = state.players.length - finished
  const ranked = useMemo(() => standings(state.players), [state.players])
  const showBoard = state.settings.leaderboard && !hideNames
  const leaders = ranked.slice(0, 5)

  return (
    <section className="host__body host__running">
      <div className="stack stack-lg" style={{ minHeight: 0 }}>
        <div className="host__stats">
          <div className="host__stat">
            <span className="host__stat-value">{state.players.length}</span>
            <span className="host__stat-label">{t('quiz.host.statJoined')}</span>
          </div>
          <div className="host__stat">
            <span className="host__stat-value">{answering}</span>
            <span className="host__stat-label">{t('quiz.host.statAnswering')}</span>
          </div>
          <div className="host__stat">
            <span className="host__stat-value">{finished}</span>
            <span className="host__stat-label">{t('quiz.host.statFinished')}</span>
          </div>
        </div>
        <div className="lanes" aria-label={t('quiz.host.lanesLabel')}>
          {state.players.map((player, index) => {
            const share = total ? Math.min(1, player.answered / total) : 0
            const done = player.status === 'finished'
            return (
              <div
                key={player.id}
                className={cx('lane', done && 'is-done', `qz-tones-${toneOf(player.name)}`)}
                style={{ '--p': share, '--step': `${100 / Math.max(1, total)}%` } as React.CSSProperties}
              >
                <span className="lane__name">{label(player, index)}</span>
                <span className="lane__track">
                  <span className="lane__trail" />
                  <span className="lane__token">
                    {done ? <Icon name="check" size={14} /> : hideNames ? index + 1 : initials(player.name)}
                  </span>
                </span>
                <span className="lane__end">
                  {player.answered}/{total}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      <aside className="host__side">
        {showBoard && leaders.length ? (
          <div className="board">
            <span className="board__title">{t('quiz.host.leaders')}</span>
            <div style={{ position: 'relative', height: leaders.length * ROW }}>
              {leaders.map((player, place) => (
                <div
                  key={player.id}
                  className="board__row"
                  style={{ position: 'absolute', left: 0, right: 0, transform: `translateY(${place * ROW}px)` }}
                >
                  <span className="board__place">{place + 1}</span>
                  <span className="board__name">{player.name}</span>
                  <span className="board__score">
                    <CountUp value={player.score} duration={600} />
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
        {teacherView ? (
          <div className="board">
            <span className="board__title">{t('quiz.host.byQuestion')}</span>
            <div className="tally">
              {state.questions.map((q) => {
                const rate = q.answered ? q.correct / q.answered : 0
                return (
                  <div key={q.id} className="tally__row" title={q.text}>
                    <span>{q.index + 1}</span>
                    <span className="tally__bar">
                      <span
                        className={cx('tally__fill', q.answered > 0 && rate < 0.5 && 'is-low')}
                        style={{ '--p': rate } as React.CSSProperties}
                      />
                    </span>
                    <span style={{ textAlign: 'right' }}>{q.answered ? `${Math.round(rate * 100)}%` : '—'}</span>
                  </div>
                )
              })}
            </div>
          </div>
        ) : null}
      </aside>
    </section>
  )
}

/* -------------------------------------------------------------- ended -- */

function Ended({
  state,
  label,
  hideNames,
  onResults,
}: {
  state: HostState
  label: (player: HostPlayer, index: number) => string
  hideNames: boolean
  onResults: () => void
}) {
  const { t } = useI18n()
  const ranked = standings(state.players)
  const total = state.questionCount || 1
  const scored = state.players.filter((p) => p.answered > 0)
  const average = scored.length
    ? Math.round((scored.reduce((sum, p) => sum + p.correct / total, 0) / scored.length) * 100)
    : null
  const podium = state.settings.leaderboard && !hideNames ? ranked.slice(0, 3) : []
  // Second, first, third - the order a podium stands in.
  const order = [1, 0, 2].filter((i) => podium[i])
  const heights = [260, 190, 140]

  return (
    <section className="host__body host__ended">
      {podium.length ? (
        <div className="podium">
          {order.map((place, slot) => {
            const player = podium[place]
            return (
              <div key={player.id} className={cx('podium__col', `qz-tones-${[3, 0, 1][place]}`)}>
                <div className="podium__who" style={{ '--who': `${1100 + (2 - place) * 450}ms` } as React.CSSProperties}>
                  <span className="podium__name">{label(player, state.players.indexOf(player))}</span>
                  <span className="podium__points">
                    {t('quiz.host.points', { n: player.score })}
                  </span>
                </div>
                <div
                  className="podium__block"
                  style={{
                    height: heights[place],
                    '--rise': `${200 + (2 - place) * 450}ms`,
                  } as React.CSSProperties}
                  data-slot={slot}
                >
                  {place + 1}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="stage__center">
          <Glyph index={2} size={80} />
          <h1 className="stage__headline">{t('quiz.host.endedTitle')}</h1>
        </div>
      )}
      <div className="stack stack-lg">
        <div className="host__stats">
          <div className="host__stat">
            <span className="host__stat-value">{state.players.length}</span>
            <span className="host__stat-label">{t('quiz.host.statJoined')}</span>
          </div>
          <div className="host__stat">
            <span className="host__stat-value">{average === null ? '—' : <><CountUp value={average} />%</>}</span>
            <span className="host__stat-label">{t('quiz.host.statAverage')}</span>
          </div>
        </div>
        <button type="button" className="stage-btn" onClick={onResults}>
          {t('quiz.host.openResults')}
          <Icon name="arrowRight" size={18} />
        </button>
        <Link className="stage-link" to={`/app/quizzes/${state.quizId}`}>
          {t('quiz.host.backToQuiz')}
        </Link>
      </div>
    </section>
  )
}
