import { cx } from '../../lib/utils'

type Tone = 'neutral' | 'info' | 'success' | 'error' | 'warning' | 'accent'

export function Badge({
  tone = 'neutral',
  children,
  className,
  title,
}: {
  tone?: Tone
  children: React.ReactNode
  className?: string
  /** Hover text, for a badge whose one word needs a sentence behind it. */
  title?: string
}) {
  return (
    <span className={cx('badge', `badge--${tone}`, className)} title={title}>
      {children}
    </span>
  )
}
