/**
 * Joining a quiz from a phone: the code, a name, and then the quiz itself.
 *
 * No account, and no app chrome - a student who scanned the projector's QR
 * code lands straight on the name field. A phone that already joined this
 * code (a refresh, a locked screen, a lost tab) finds its token in local
 * storage and goes back in as the same player.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { LanguageMenu } from '../../components/layout/LanguageMenu'
import { useI18n } from '../../lib/i18n'
import { useStore } from '../../lib/store'
import { cx } from '../../lib/utils'
import { QuizError, joinRun, keepToken, lookupCode, playState, savedToken } from '../api'
import { Glyph } from '../glyphs'
import { useServerPlayer } from '../play/controller'
import { PlayerView } from '../play/PlayerView'
import type { CodeLookup } from '../types'
import '../quiz.css'

const ALPHABET = 'ACDEFGHJKMNPQRTUVWXY34679'
const LENGTH = 6

function cleanCode(raw: string): string {
  return raw
    .toUpperCase()
    .split('')
    .filter((c) => ALPHABET.includes(c))
    .join('')
    .slice(0, LENGTH)
}

type Step = 'code' | 'name' | 'play'

export function Join() {
  const { code: routeCode } = useParams()
  const navigate = useNavigate()
  const { t } = useI18n()
  const { user } = useStore()

  const [step, setStep] = useState<Step>('code')
  const [code, setCode] = useState(() => cleanCode(routeCode ?? ''))
  const [found, setFound] = useState<CodeLookup | null>(null)
  const [name, setName] = useState('')
  const [token, setToken] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [shake, setShake] = useState(0)
  const [busy, setBusy] = useState(false)

  // A signed-in student's own name, offered once rather than imposed: after
  // that the field is theirs, and clearing it must not fill it back in.
  const offered = useRef(false)
  useEffect(() => {
    if (offered.current || !user?.name) return
    offered.current = true
    setName((current) => current || user.name)
  }, [user])

  const describe = useCallback(
    (failure: unknown): string => {
      if (!(failure instanceof QuizError)) return t('quiz.join.error')
      switch (failure.code) {
        case 'no_such_code':
          return t('quiz.join.noCode')
        case 'late_join_closed':
          return t('quiz.join.closed')
        case 'session_full':
          return t('quiz.join.full')
        case 'slow_down':
          return t('quiz.join.slowDown')
        case 'no_name':
          return t('quiz.join.nameNeeded')
        default:
          return failure.status === 0 ? t('quiz.join.offline') : t('quiz.join.error')
      }
    },
    [t],
  )

  const findCode = useCallback(
    async (value: string) => {
      setBusy(true)
      setError('')
      try {
        const lookup = await lookupCode(value)
        setFound(lookup)
        // Back in as the same player, if this phone has been here before.
        const kept = savedToken(lookup.code)
        if (kept) {
          try {
            const state = await playState(kept)
            if (state.status !== 'kicked') {
              setToken(kept)
              setStep('play')
              return
            }
          } catch {
            keepToken(lookup.code, null)
          }
        }
        if (!lookup.joinable) {
          setError(t('quiz.join.closed'))
          return
        }
        setStep('name')
        if (routeCode !== lookup.code) navigate(`/join/${lookup.code}`, { replace: true })
      } catch (failure) {
        setError(describe(failure))
        setShake((n) => n + 1)
      } finally {
        setBusy(false)
      }
    },
    [describe, navigate, routeCode, t],
  )

  // Arriving from the QR code: the code is already in the address.
  const tried = useRef(false)
  useEffect(() => {
    if (tried.current) return
    tried.current = true
    if (code.length === LENGTH) void findCode(code)
  }, [code, findCode])

  async function onJoin(event: React.FormEvent) {
    event.preventDefault()
    if (!found) return
    const chosen = name.trim()
    if (!chosen) {
      setError(t('quiz.join.nameNeeded'))
      return
    }
    setBusy(true)
    setError('')
    try {
      const joined = await joinRun(found.code, chosen)
      keepToken(found.code, joined.token)
      setToken(joined.token)
      setStep('play')
    } catch (failure) {
      setError(describe(failure))
    } finally {
      setBusy(false)
    }
  }

  const leave = useCallback(() => {
    if (found) keepToken(found.code, null)
    setToken(null)
    setFound(null)
    setCode('')
    setStep('code')
    navigate('/join', { replace: true })
  }, [found, navigate])

  return (
    <div className="stage">
      <div className="qz-band" />
      <div className="stage__bar">
        <Glyph index={0} size={22} />
        <span className="stage__title">{found?.title || t('quiz.join.brand')}</span>
        <span className="grow" />
        {step !== 'play' ? <LanguageMenu side="bottom" align="end" /> : null}
      </div>
      <main className="stage__body">
        {step === 'play' && token ? (
          <Playing token={token} onGone={leave} />
        ) : step === 'name' && found ? (
          <form className="stage__center" onSubmit={onJoin}>
            <span className="stage-pill">
              {t('quiz.join.facts', { n: found.questionCount })}
              {found.timeLimitMin ? ` · ${t('quiz.join.minutes', { n: found.timeLimitMin })}` : ''}
            </span>
            <h1 className="stage__headline">{found.title}</h1>
            <label className="stage__lead" htmlFor="quiz-name">
              {t('quiz.join.nameLabel')}
            </label>
            <input
              id="quiz-name"
              className="stage-input"
              value={name}
              maxLength={24}
              autoComplete="nickname"
              autoFocus
              placeholder={t('quiz.join.namePlaceholder')}
              onChange={(event) => setName(event.target.value)}
            />
            <p className="stage-error" role="alert">
              {error}
            </p>
            <button type="submit" className="stage-btn stage-btn--go stage-btn--block" disabled={busy}>
              {t('quiz.join.go')}
            </button>
            <button type="button" className="stage-link" onClick={leave}>
              {t('quiz.join.otherCode')}
            </button>
          </form>
        ) : (
          <div className="stage__center">
            <h1 className="stage__headline">{t('quiz.join.title')}</h1>
            <p className="stage__lead">{t('quiz.join.lead')}</p>
            <CodeEntry
              key={shake}
              value={code}
              wrong={shake > 0 && Boolean(error)}
              disabled={busy}
              onChange={(value) => {
                setCode(value)
                setError('')
                if (value.length === LENGTH) void findCode(value)
              }}
            />
            <p className="stage-error" role="alert">
              {error}
            </p>
          </div>
        )}
      </main>
    </div>
  )
}

function Playing({ token, onGone }: { token: string; onGone: () => void }) {
  const ctl = useServerPlayer(token, onGone)
  return <PlayerView ctl={ctl} onLeave={onGone} />
}

/**
 * Six cells over one real, invisible input: the phone's keyboard, paste and
 * autofill all work as in any field, and the cells only draw what it holds.
 */
function CodeEntry({
  value,
  wrong,
  disabled,
  onChange,
}: {
  value: string
  wrong: boolean
  disabled: boolean
  onChange: (value: string) => void
}) {
  const { t } = useI18n()
  const inputRef = useRef<HTMLInputElement>(null)
  const [focused, setFocused] = useState(false)

  return (
    <div className={cx('qz-entry', wrong && 'is-wrong')} onClick={() => inputRef.current?.focus()}>
      {Array.from({ length: LENGTH }, (_, i) => (
        <span
          key={i}
          className={cx(
            'qz-entry__cell',
            value[i] && 'is-filled',
            focused && i === Math.min(value.length, LENGTH - 1) && !value[i] && 'is-cursor',
          )}
        >
          {value[i] ?? ''}
        </span>
      ))}
      <input
        ref={inputRef}
        className="qz-entry__input"
        value={value}
        disabled={disabled}
        autoFocus
        autoCapitalize="characters"
        autoCorrect="off"
        autoComplete="one-time-code"
        spellCheck={false}
        inputMode="text"
        aria-label={t('quiz.join.codeLabel')}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(event) => onChange(cleanCode(event.target.value))}
      />
    </div>
  )
}
