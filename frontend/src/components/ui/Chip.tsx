import { cx } from '../../lib/utils'

interface ChipProps extends Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  'onChange'
> {
  selected: boolean
  children: React.ReactNode
}

/** Toggleable filter chip. Uses aria-pressed so the state is announced. */
export function Chip({ selected, children, className, ...rest }: ChipProps) {
  return (
    <button
      {...rest}
      type="button"
      aria-pressed={selected}
      className={cx('chip', className)}
    >
      {children}
    </button>
  )
}

export function ChipGroup({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="chip-group" role="group" aria-label={label}>
      {children}
    </div>
  )
}
