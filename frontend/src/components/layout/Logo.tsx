import { Link } from 'react-router-dom'
import { cx } from '../../lib/utils'
import logoUrl from '../../assets/logo.png'

/** Intrinsic size of the supplied artwork, used to keep its aspect ratio. */
const MARK_W = 432
const MARK_H = 369

interface LogoProps {
  to?: string
  className?: string
  /** Width of the mark in pixels; the height follows the artwork's ratio. */
  size?: number
  /** Hides the wordmark, leaving just the mark. */
  markOnly?: boolean
}

/** The Anyq lockup: the supplied mark, plus the wordmark. */
export function Logo({ to = '/', className, size = 32, markOnly = false }: LogoProps) {
  return (
    <Link to={to} className={cx('logo', className)} aria-label="Anyq AI">
      <img
        src={logoUrl}
        alt=""
        className="logo__mark"
        width={size}
        height={Math.round((size * MARK_H) / MARK_W)}
      />

      {markOnly ? null : (
        <span className="logo__word">
          ANYQ<span className="logo__word-ai">AI</span>
        </span>
      )}
    </Link>
  )
}
