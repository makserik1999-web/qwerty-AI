import { cx } from '../../lib/utils'
import { Icon, type IconName } from './Icon'

type Tone = 'info' | 'success' | 'warning' | 'error'

const TONE_ICON: Record<Tone, IconName> = {
  info: 'info',
  success: 'checkCircle',
  warning: 'warning',
  error: 'alert',
}

interface AlertProps {
  tone?: Tone
  title?: string
  children: React.ReactNode
  action?: React.ReactNode
  className?: string
  /** Set for messages that appear as the result of a user action. */
  live?: boolean
}

export function Alert({
  tone = 'info',
  title,
  children,
  action,
  className,
  live = false,
}: AlertProps) {
  return (
    <div
      className={cx('alert', `alert--${tone}`, className)}
      role={tone === 'error' ? 'alert' : live ? 'status' : undefined}
      aria-live={live && tone !== 'error' ? 'polite' : undefined}
    >
      <span className="alert__icon">
        <Icon name={TONE_ICON[tone]} size={18} />
      </span>
      <div className="stack stack-sm grow">
        {title ? <strong>{title}</strong> : null}
        <div>{children}</div>
        {action}
      </div>
    </div>
  )
}
