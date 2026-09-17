import { forwardRef } from 'react'
import { Link } from 'react-router-dom'
import { cx } from '../../lib/utils'
import { Icon, type IconName } from './Icon'
import { Spinner } from './Spinner'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'quietDanger'
type Size = 'sm' | 'md' | 'lg'

const VARIANT_CLASS: Record<Variant, string> = {
  primary: 'btn--primary',
  secondary: 'btn--secondary',
  ghost: 'btn--ghost',
  danger: 'btn--danger',
  quietDanger: 'btn--quiet-danger',
}

interface CommonProps {
  variant?: Variant
  size?: Size
  block?: boolean
  icon?: IconName
  iconAfter?: IconName
  loading?: boolean
  children?: React.ReactNode
  className?: string
}

type ButtonProps = CommonProps &
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'className'>

function content({ icon, iconAfter, loading, children }: CommonProps) {
  return (
    <>
      {loading ? <Spinner /> : icon ? <Icon name={icon} size={18} /> : null}
      {children}
      {iconAfter && !loading ? <Icon name={iconAfter} size={18} /> : null}
    </>
  )
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    block,
    icon,
    iconAfter,
    loading = false,
    children,
    className,
    disabled,
    type = 'button',
    ...rest
  },
  ref,
) {
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cx(
        'btn',
        VARIANT_CLASS[variant],
        `btn--${size}`,
        block && 'btn--block',
        className,
      )}
    >
      {content({ icon, iconAfter, loading, children })}
    </button>
  )
})

type LinkButtonProps = CommonProps & {
  to: string
} & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'children' | 'className' | 'href'>

/** Same visual treatment as Button, but renders a real link for navigation. */
export function LinkButton({
  to,
  variant = 'secondary',
  size = 'md',
  block,
  icon,
  iconAfter,
  children,
  className,
  ...rest
}: LinkButtonProps) {
  return (
    <Link
      {...rest}
      to={to}
      className={cx(
        'btn',
        VARIANT_CLASS[variant],
        `btn--${size}`,
        block && 'btn--block',
        className,
      )}
    >
      {content({ icon, iconAfter, children })}
    </Link>
  )
}

type AnchorButtonProps = CommonProps & React.AnchorHTMLAttributes<HTMLAnchorElement>

/** Button styling for a plain anchor — in-page links, downloads, mailto. */
export function AnchorButton({
  variant = 'secondary',
  size = 'md',
  block,
  icon,
  iconAfter,
  children,
  className,
  ...rest
}: AnchorButtonProps) {
  return (
    <a
      {...rest}
      className={cx(
        'btn',
        VARIANT_CLASS[variant],
        `btn--${size}`,
        block && 'btn--block',
        className,
      )}
    >
      {content({ icon, iconAfter, children })}
    </a>
  )
}

interface IconButtonProps extends Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  'children'
> {
  icon: IconName
  label: string
  variant?: Variant
}

export function IconButton({
  icon,
  label,
  variant = 'ghost',
  className,
  type = 'button',
  ...rest
}: IconButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      aria-label={label}
      title={label}
      className={cx('btn', VARIANT_CLASS[variant], 'btn--icon', className)}
    >
      <Icon name={icon} size={18} />
    </button>
  )
}
