import { cx, initialsOf } from '../../lib/utils'

export function Avatar({
  name,
  size = 'md',
  className,
}: {
  name: string
  size?: 'md' | 'lg'
  className?: string
}) {
  return (
    <span
      className={cx('avatar', size === 'lg' && 'avatar--lg', className)}
      aria-hidden="true"
    >
      {initialsOf(name)}
    </span>
  )
}
