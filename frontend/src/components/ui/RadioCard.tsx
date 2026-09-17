import { cx } from '../../lib/utils'
import { Icon, type IconName } from './Icon'

interface RadioCardProps {
  name: string
  value: string
  checked: boolean
  onChange: (value: string) => void
  title: string
  description?: string
  icon?: IconName
  className?: string
}

/**
 * A large selectable card backed by a real radio input, so grouping, keyboard
 * behaviour and screen-reader semantics come for free.
 */
export function RadioCard({
  name,
  value,
  checked,
  onChange,
  title,
  description,
  icon,
  className,
}: RadioCardProps) {
  return (
    <label className={cx('radio-card', checked && 'is-checked', className)}>
      <input
        type="radio"
        className="visually-hidden"
        name={name}
        value={value}
        checked={checked}
        onChange={() => onChange(value)}
      />
      <span className="radio-card__mark" aria-hidden="true">
        {checked ? <Icon name="check" size={14} /> : null}
      </span>
      <span className="radio-card__body">
        <span className="radio-card__title">
          {icon ? <Icon name={icon} size={18} /> : null}
          {title}
        </span>
        {description ? <span className="radio-card__desc">{description}</span> : null}
      </span>
    </label>
  )
}
