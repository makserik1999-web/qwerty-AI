import { cx } from '../../lib/utils'

export function Spinner({ size = 'sm', label }: { size?: 'sm' | 'lg'; label?: string }) {
  return (
    <span
      className={cx('spinner', size === 'lg' && 'spinner--lg')}
      role={label ? 'status' : undefined}
      aria-label={label}
    />
  )
}
