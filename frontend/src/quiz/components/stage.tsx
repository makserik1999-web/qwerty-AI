/**
 * Pieces the projector and the phones share.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { MarkdownMessage } from '../../components/MarkdownMessage'
import { Icon } from '../../components/ui'
import { cx } from '../../lib/utils'
import { Glyph, letterOf } from '../glyphs'
import { prefersReducedMotion } from '../live'
import { encodeQr, qrPath } from '../qr'

/* -------------------------------------------------------- code board -- */

/**
 * The join code as a station departure board: each character clacks into
 * place in turn. Remounting (a new `code`) plays it again.
 */
export function CodeBoard({ code, className }: { code: string; className?: string }) {
  return (
    <div className={cx('qz-code', className)} aria-label={code.split('').join(' ')} role="img">
      {code.split('').map((char, i) => (
        <span key={`${code}-${i}`} className="qz-code__cell" style={{ '--i': i } as React.CSSProperties}>
          {char}
        </span>
      ))}
    </div>
  )
}

/* ---------------------------------------------------------------- QR -- */

export function QrCode({ text, label }: { text: string; label: string }) {
  const { size, path } = useMemo(() => {
    const matrix = encodeQr(text)
    return { size: matrix.size + 8, path: qrPath(matrix, 4) }
  }, [text])
  return (
    <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#ffffff" />
      <path d={path} fill="#0c1530" />
    </svg>
  )
}

/* ---------------------------------------------------------- countdown -- */

/**
 * Seconds until `target`, drawn as a number and a ring. The number remounts
 * each second so its beat animation plays once per second, in step with the
 * projector and every other phone - they all count to the same server time.
 */
export function Countdown({ remainingMs, totalMs }: { remainingMs: number; totalMs: number }) {
  const seconds = Math.max(1, Math.ceil(remainingMs / 1000))
  const radius = 46
  const circumference = 2 * Math.PI * radius
  const share = Math.max(0, Math.min(1, remainingMs / Math.max(1, totalMs)))
  return (
    <div className="qz-countdown" aria-live="assertive">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle className="qz-countdown__track" cx="50" cy="50" r={radius} />
        <circle
          className="qz-countdown__sweep"
          cx="50"
          cy="50"
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - share)}
        />
      </svg>
      <span key={seconds} className="qz-countdown__number">
        {seconds}
      </span>
    </div>
  )
}

/* -------------------------------------------------------------- tiles -- */

export interface TileOption {
  id: string
  text: string
}

interface TilesProps {
  options: TileOption[]
  picked?: string | null
  rightId?: string | null
  locked?: boolean
  onPick?: (id: string) => void
  /** Accessible name for each option: "A: 5 m/s²". */
  labelFor?: (index: number, text: string) => string
}

/**
 * The answer tiles. Long options get a single column - two columns of
 * sentences on a phone is a wall of text in two colours.
 */
export function AnswerTiles({ options, picked, rightId, locked, onPick, labelFor }: TilesProps) {
  const long = options.some((o) => o.text.length > 34)
  return (
    <div
      className={cx('qz-answers', long && 'qz-answers--list', locked && 'is-locked')}
      role="group"
    >
      {options.map((option, index) => {
        const isPicked = picked === option.id
        const isRight = Boolean(rightId) && rightId === option.id
        const isWrong = Boolean(rightId) && isPicked && !isRight
        return (
          <button
            key={option.id}
            type="button"
            className={cx(
              'qz-tile',
              `qz-tones-${index % 4}`,
              isPicked && 'is-picked',
              isRight && 'is-right',
              isWrong && 'is-wrong',
            )}
            style={{ '--i': index } as React.CSSProperties}
            disabled={locked}
            aria-pressed={isPicked}
            aria-label={labelFor ? labelFor(index, option.text) : `${letterOf(index)}: ${option.text}`}
            onClick={() => onPick?.(option.id)}
          >
            <span className="qz-tile__mark">
              <Glyph index={index} size={26} />
            </span>
            <span className="qz-tile__text">
              <MarkdownMessage content={option.text} />
            </span>
            <span className="qz-tile__verdict" aria-hidden="true">
              <Icon name={isWrong ? 'close' : 'check'} size={18} />
            </span>
          </button>
        )
      })}
    </div>
  )
}

/* ----------------------------------------------------------- count up -- */

/** A number that rolls up to its value, once, on an ease-out curve. */
export function CountUp({ value, duration = 1400 }: { value: number; duration?: number }) {
  const [shown, setShown] = useState(prefersReducedMotion() ? value : 0)
  const from = useRef(0)

  useEffect(() => {
    if (prefersReducedMotion()) {
      setShown(value)
      return
    }
    const start = performance.now()
    const begin = from.current
    let frame = 0
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 4)
      setShown(Math.round(begin + (value - begin) * eased))
      if (t < 1) frame = requestAnimationFrame(step)
      else from.current = value
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [value, duration])

  return <>{shown}</>
}

/* -------------------------------------------------------------- misc -- */

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

/** A stable tone for a name, so a student keeps their colour all lesson. */
export function toneOf(key: string): number {
  let hash = 0
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0
  return hash % 4
}

/** Rendered question text: the model writes formulas in LaTeX. */
export function QuestionText({ text }: { text: string }) {
  return <MarkdownMessage content={text} />
}

export function formatSeconds(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
