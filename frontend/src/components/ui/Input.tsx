import { forwardRef } from 'react'
import { cx } from '../../lib/utils'
import { Icon } from './Icon'

export const Input = forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function Input({ className, ...rest }, ref) {
  return <input {...rest} ref={ref} className={cx('input', className)} />
})

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...rest }, ref) {
  return <textarea {...rest} ref={ref} className={cx('textarea', className)} />
})

interface SearchInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string
}

/** Search field with a leading icon and a visually hidden label. */
export function SearchInput({ label, className, id, ...rest }: SearchInputProps) {
  const inputId = id ?? 'search-input'
  return (
    <div className={cx('search', className)}>
      <label className="visually-hidden" htmlFor={inputId}>
        {label}
      </label>
      <span className="search__icon">
        <Icon name="search" size={18} />
      </span>
      <input {...rest} id={inputId} type="search" className="input" />
    </div>
  )
}
