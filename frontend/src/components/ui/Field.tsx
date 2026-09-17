import { useId } from 'react'
import { cx } from '../../lib/utils'
import { Icon } from './Icon'

interface FieldProps {
  label: string
  hint?: string
  error?: string
  /** Renders the control; receives the ids it must wire up. */
  children: (props: {
    id: string
    'aria-describedby': string | undefined
    'aria-invalid': boolean | undefined
  }) => React.ReactNode
  className?: string
}

/**
 * Label + control + hint/error, wired together with ids so screen readers
 * announce the description and the error with the control.
 */
export function Field({ label, hint, error, children, className }: FieldProps) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  return (
    <div className={cx('field', className)}>
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {children({
        id,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : undefined,
      })}
      {hint && !error ? (
        <p className="field__hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="field__error" id={errorId}>
          <Icon name="alert" size={15} />
          {error}
        </p>
      ) : null}
    </div>
  )
}
