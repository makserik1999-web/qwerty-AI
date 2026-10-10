import { Icon, type IconName } from './Icon'

interface EmptyStateProps {
  icon?: IconName
  title: string
  body?: string
  action?: React.ReactNode
  /** Heading level, so the page keeps a correct outline. */
  level?: 2 | 3
}

export function EmptyState({
  icon = 'lightbulb',
  title,
  body,
  action,
  level = 3,
}: EmptyStateProps) {
  const Heading = `h${level}` as 'h2' | 'h3'
  return (
    <div className="empty">
      <span className="empty__icon">
        <Icon name={icon} size={24} />
      </span>
      <Heading className="card__title">{title}</Heading>
      {body ? <p className="empty__body">{body}</p> : null}
      {action}
    </div>
  )
}
