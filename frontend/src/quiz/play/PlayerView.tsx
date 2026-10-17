/**
 * A student's screens, from the lobby to the score.
 *
 * Driven by a PlayController, so the teacher's preview and a real phone run
 * exactly this code. Everything time-based is drawn against the controller's
 * clock, which on a real phone is the server's.
 */
import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/ui'
import { useI18n } from '../../lib/i18n'
import { cx } from '../../lib/utils'
import {
  AnswerTiles,
  CountUp,
  Countdown,
  QuestionText,
  formatSeconds,
  initials,
  toneOf,
} from '../components/stage'
import { Glyph, letterOf } from '../glyphs'
import { useTicker } from '../live'
import type { PlayState } from '../types'
import type { Feedback, PlayController } from './controller'

const COUNTDOWN_TOTAL_MS = 4000

interface Props {
  ctl: PlayController
  /** Leave this quiz and go back to entering a code. */
  onLeave?: () => void
  /** Inside the teacher's phone frame: no leaving, a restart instead. */
  preview?: { onRestart: () => void }
}

export function PlayerView({ ctl, onLeave, preview }: Props) {
  const { t } = useI18n()
  const state = ctl.state

  if (!state) {
    return (
      <div className="stage__center">
        <div className="qz-wait">
          <span className="qz-wait__ring" />
          <span className="qz-wait__ring" />
          <Glyph index={0} size={64} className="qz-wait__glyph" />
        </div>
      </div>
    )
  }

  return (
    <>
      {ctl.failed ? (
        <div className="stage-pill stage-pill--warn" role="status" style={{ alignSelf: 'center' }}>
          <Icon name="refresh" size={14} />
          {t('quiz.play.reconnecting')}
        </div>
      ) : null}
      {ctl.feedback || state.status === 'playing' ? (
        <QuestionScreen ctl={ctl} state={state} />
      ) : state.status === 'lobby' ? (
        <LobbyScreen state={state} players={ctl.players} />
      ) : state.status === 'countdown' ? (
        <CountdownScreen state={state} now={ctl.now} />
      ) : state.status === 'finished' ? (
        <FinishedScreen state={state} history={ctl.history} preview={preview} />
      ) : (
        <div className="stage__center">
          <Glyph index={1} size={56} />
          <h1 className="stage__headline">{t('quiz.play.removedTitle')}</h1>
          <p className="stage__lead">{t('quiz.play.removedBody')}</p>
          {onLeave ? (
            <button type="button" className="stage-btn" onClick={onLeave}>
              {t('quiz.play.otherCode')}
            </button>
          ) : null}
        </div>
      )}
    </>
  )
}

/* ------------------------------------------------------------- lobby -- */

function LobbyScreen({ state, players }: { state: PlayState; players: number }) {
  const { t } = useI18n()
  const tone = toneOf(state.player.name)
  return (
    <div className="stage__center">
      <div className="qz-wait">
        <span className="qz-wait__ring" />
        <span className="qz-wait__ring" />
        <Glyph index={0} size={72} className="qz-wait__glyph" />
      </div>
      <div className={cx('qz-me', `qz-tones-${tone}`)}>
        <span className="qz-avatar">{initials(state.player.name)}</span>
        {state.player.name}
      </div>
      <h1 className="stage__headline">{t('quiz.play.inTitle')}</h1>
      <p className="stage__lead">{t('quiz.play.inBody')}</p>
      {players > 1 ? (
        <span className="stage-pill">{t('quiz.play.lobbyCount', { n: players })}</span>
      ) : null}
    </div>
  )
}

/* --------------------------------------------------------- countdown -- */

function CountdownScreen({ state, now }: { state: PlayState; now: () => number }) {
  const { t } = useI18n()
  useTicker(true, 100)
  const remaining = state.startsAt ? Date.parse(state.startsAt) - now() : 0
  return (
    <div className="stage__center">
      <p className="stage__lead">{t('quiz.play.getReady')}</p>
      <Countdown remainingMs={remaining} totalMs={COUNTDOWN_TOTAL_MS} />
      <p className="stage__lead">
        {t('quiz.play.questionsAhead', { n: state.questionCount })}
      </p>
    </div>
  )
}

/* ---------------------------------------------------------- question -- */

function QuestionScreen({ ctl, state }: { ctl: PlayController; state: PlayState }) {
  const { t } = useI18n()
  const feedback = ctl.feedback
  const question = feedback?.question ?? state.question
  const [typed, setTyped] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  useTicker(Boolean(state.deadline) && !feedback, 500)

  useEffect(() => {
    setTyped('')
    if (question?.type === 'short') inputRef.current?.focus()
  }, [question?.id, question?.type])

  if (!question) return null

  const progress = feedback ? feedback.next.progress : state.progress
  const remaining = state.deadline ? (Date.parse(state.deadline) - ctl.now()) / 1000 : null
  const picked = feedback?.pickedId ?? null
  const rightId = feedback?.reveal?.correctOptionId ?? null
  const streak = progress.streak

  return (
    <>
      <div className="qz-head">
        <div className="qz-head__row">
          <span className="stage-pill">
            {question.index + 1} / {question.total}
          </span>
          {state.showResults && streak >= 2 ? (
            <span key={streak} className="stage-pill qz-streak is-hot">
              <Glyph index={3} size={16} />
              {t('quiz.play.streak', { n: streak })}
            </span>
          ) : null}
          <span className="grow" />
          {remaining !== null && !feedback ? (
            <span
              className={cx('stage-pill', remaining < 60 && 'stage-pill--warn')}
              aria-label={t('quiz.play.timeLeft')}
            >
              <Icon name="clock" size={14} />
              {formatSeconds(remaining)}
            </span>
          ) : null}
          {state.showResults ? (
            <span className="stage-pill" aria-label={t('quiz.play.score')}>
              <CountUp value={progress.score} duration={700} />
            </span>
          ) : null}
        </div>
        <div className="qz-segs" aria-hidden="true">
          {Array.from({ length: question.total }, (_, i) => {
            const done = i < progress.answered
            const verdict = ctl.trail[i]
            return (
              <span
                key={i}
                className={cx(
                  'qz-seg',
                  done && 'is-done',
                  done && verdict === true && 'is-right',
                  done && verdict === false && 'is-wrong',
                  i === question.index && !feedback && 'is-now',
                )}
              />
            )
          })}
        </div>
      </div>

      <div className="qz-question" key={question.id}>
        <QuestionText text={question.text} />
      </div>

      <div style={{ position: 'relative' }}>
        {question.type === 'choice' ? (
          <AnswerTiles
            options={question.options ?? []}
            picked={picked}
            rightId={rightId}
            locked={Boolean(feedback) || ctl.busy}
            onPick={(id) => {
              vibrate(10)
              ctl.answer({ optionId: id })
            }}
            labelFor={(i, text) => `${letterOf(i)}: ${text}`}
          />
        ) : (
          <form
            className={cx(
              'qz-typed',
              feedback?.correct === true && 'is-right',
              feedback?.correct === false && !feedback.skipped && 'is-wrong',
            )}
            onSubmit={(event) => {
              event.preventDefault()
              if (typed.trim()) ctl.answer({ text: typed.trim() })
            }}
          >
            <div className="qz-typed__field">
              <input
                ref={inputRef}
                className="stage-input"
                value={feedback ? feedback.typed : typed}
                onChange={(event) => setTyped(event.target.value)}
                placeholder={t('quiz.play.typeAnswer')}
                aria-label={t('quiz.play.typeAnswer')}
                inputMode="text"
                autoComplete="off"
                maxLength={60}
                disabled={Boolean(feedback) || ctl.busy}
              />
              {question.unit ? <span className="qz-typed__unit">{question.unit}</span> : null}
            </div>
            {feedback ? null : (
              <button
                type="submit"
                className="stage-btn stage-btn--block"
                disabled={!typed.trim() || ctl.busy}
              >
                {t('quiz.play.send')}
              </button>
            )}
          </form>
        )}
        {feedback?.correct && feedback.points ? (
          <span key={question.id} className="qz-points" aria-hidden="true">
            +{feedback.points}
          </span>
        ) : null}
      </div>

      {feedback ? (
        <FeedbackPanel feedback={feedback} onNext={ctl.next} />
      ) : (
        <div style={{ textAlign: 'center', marginTop: 18 }}>
          <button
            type="button"
            className="stage-link"
            disabled={ctl.busy}
            onClick={() => ctl.answer({ skip: true })}
          >
            {t('quiz.play.skip')}
          </button>
        </div>
      )}
    </>
  )
}

function vibrate(pattern: number | number[]) {
  try {
    navigator.vibrate?.(pattern)
  } catch {
    /* not on this device */
  }
}

/** What the student is told after answering, and the way on. */
function FeedbackPanel({ feedback, onNext }: { feedback: Feedback; onNext: () => void }) {
  const { t } = useI18n()
  const hidden = feedback.correct === null
  // Long enough to read the explanation after a wrong answer, short after a
  // right one; with results hidden there is nothing to read at all.
  const wait = hidden ? 900 : feedback.correct ? 2600 : feedback.reveal?.explanation ? 6500 : 3200

  // Through a ref: the timer belongs to this answer, and must not restart
  // because the parent re-rendered and handed over a new function.
  const nextRef = useRef(onNext)
  nextRef.current = onNext
  useEffect(() => {
    if (feedback.correct !== null) vibrate(feedback.correct ? 25 : [40, 70, 40])
    const id = window.setTimeout(() => nextRef.current(), wait)
    return () => window.clearTimeout(id)
  }, [feedback, wait])

  if (hidden) {
    return (
      <div className="qz-reveal" role="status">
        <div className="qz-reveal__verdict">
          <Icon name="check" size={20} />
          {t('quiz.play.received')}
        </div>
      </div>
    )
  }

  const shortAnswer = feedback.question.type === 'short' ? feedback.reveal?.answer : ''
  return (
    <div role="status">
      <div className="qz-reveal">
        <div className={cx('qz-reveal__verdict', feedback.correct ? 'is-right' : 'is-wrong')}>
          <Icon name={feedback.correct ? 'checkCircle' : 'alert'} size={22} />
          {feedback.correct
            ? t('quiz.play.right')
            : feedback.skipped
              ? t('quiz.play.skipped')
              : t('quiz.play.wrong')}
        </div>
        {!feedback.correct && shortAnswer ? (
          <div className="qz-reveal__body">
            {t('quiz.play.rightAnswer')}: <strong>{shortAnswer}</strong>
          </div>
        ) : null}
        {feedback.reveal?.explanation ? (
          <div className="qz-reveal__body">
            <QuestionText text={feedback.reveal.explanation} />
          </div>
        ) : null}
      </div>
      <button
        type="button"
        className="stage-btn stage-btn--block qz-next"
        onClick={onNext}
        style={{ '--wait': `${wait}ms` } as React.CSSProperties}
      >
        {t('quiz.play.next')}
        <Icon name="arrowRight" size={18} />
        <span key={feedback.question.id} className="qz-next__timer" />
      </button>
    </div>
  )
}

/* ---------------------------------------------------------- finished -- */

function FinishedScreen({
  state,
  history,
  preview,
}: {
  state: PlayState
  history: Record<string, boolean | null>
  preview?: { onRestart: () => void }
}) {
  const { t } = useI18n()
  const result = state.result
  if (!result) return null
  const shown = result.score !== undefined

  return (
    <div className="stage__center">
      {shown ? (
        <>
          <p className="stage__lead">
            {result.answered < result.total ? t('quiz.play.timeUp') : t('quiz.play.done')}
          </p>
          <div className="qz-score" aria-label={t('quiz.play.score')}>
            <CountUp value={result.score ?? 0} />
          </div>
          <p className="stage__lead">
            {t('quiz.play.correctOf', { n: result.correct ?? 0, total: result.total })}
          </p>
          <div className="qz-dots" aria-hidden="true">
            {(result.answers ?? []).map((a, i) => {
              const verdict = a.correct ?? history[a.questionId] ?? null
              return (
                <span
                  key={a.questionId}
                  className={cx('qz-dot', verdict === true && 'is-right', verdict === false && 'is-wrong')}
                  style={{ '--i': i } as React.CSSProperties}
                />
              )
            })}
          </div>
          {result.rank ? (
            <div className="qz-place">
              <strong>{result.rank}</strong>
              {t('quiz.play.placeOf', { n: result.of ?? result.rank })}
            </div>
          ) : null}
        </>
      ) : (
        <>
          <Glyph index={2} size={64} />
          <h1 className="stage__headline">{t('quiz.play.sentTitle')}</h1>
          <p className="stage__lead">{t('quiz.play.sentBody')}</p>
        </>
      )}
      {result.waiting && !preview ? (
        <p className="stage__lead">
          <span className="qz-pulse" /> {t('quiz.play.othersFinishing')}
        </p>
      ) : null}
      {preview ? (
        <button type="button" className="stage-btn stage-btn--quiet stage-btn--sm" onClick={preview.onRestart}>
          <Icon name="replay" size={16} />
          {t('quiz.preview.again')}
        </button>
      ) : null}
    </div>
  )
}
