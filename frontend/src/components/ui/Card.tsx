import { cx } from '../../lib/utils'

type Elevation = 'flat' | 'raised' | 'floating'

interface CardProps extends React.HTMLAttributes<HTMLElement> {
  elevation?: Elevation
  /** Removes the inner padding — for cards whose child manages its own layout. */
  plain?: boolean
  as?: 'div' | 'section' | 'article' | 'li'
}

export function Card({
  elevation = 'flat',
  plain = false,
  as = 'div',
  className,
  children,
  ...rest
}: CardProps) {
  const Tag = as as React.ElementType
  return (
    <Tag
      {...rest}
      className={cx('card', `card--${elevation}`, plain && 'card--plain', className)}
    >
      {children}
    </Tag>
  )
}

export function CardHeader({
  title,
  subtitle,
  actions,
  level = 2,
}: {
  title: string
  subtitle?: string
  actions?: React.ReactNode
  level?: 2 | 3 | 4
}) {
  const Heading = `h${level}` as 'h2' | 'h3' | 'h4'
  return (
    <div className="card__header">
      <div className="stack stack-sm">
        <Heading className="card__title">{title}</Heading>
        {subtitle ? <p className="card__subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="row row--actions">{actions}</div> : null}
    </div>
  )
}
