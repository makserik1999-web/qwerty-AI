import { cx } from '../../lib/utils'

type Tone = 'neutral' | 'info' | 'success' | 'error' | 'warning' | 'accent'

export function Badge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: Tone
  children: React.ReactNode
  className?: string
}) {
  return <span className={cx('badge', `badge--${tone}`, className)}>{children}</span>
}
