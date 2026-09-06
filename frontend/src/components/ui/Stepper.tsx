import { clamp } from '../../lib/utils'
import { IconButton } from './Button'

interface StepperProps {
  value: number
  min?: number
  max?: number
  step?: number
  onChange: (value: number) => void
  label: string
  decreaseLabel: string
  increaseLabel: string
  id?: string
  'aria-describedby'?: string
}

/** Numeric stepper exposed as a spinbutton. */
export function Stepper({
  value,
  min = 1,
  max = 20,
  step = 1,
  onChange,
  label,
  decreaseLabel,
  increaseLabel,
  id,
  ...aria
}: StepperProps) {
  function move(delta: number) {
    onChange(clamp(value + delta, min, max))
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'ArrowUp' || event.key === 'ArrowRight') {
      event.preventDefault()
      move(step)
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') {
      event.preventDefault()
      move(-step)
    } else if (event.key === 'Home') {
      event.preventDefault()
      onChange(min)
    } else if (event.key === 'End') {
      event.preventDefault()
      onChange(max)
    }
  }

  return (
    <div
      className="stepper"
      role="spinbutton"
      id={id}
      tabIndex={0}
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-describedby={aria['aria-describedby']}
      onKeyDown={onKeyDown}
    >
      <IconButton
        icon="minus"
        label={decreaseLabel}
        tabIndex={-1}
        disabled={value <= min}
        onClick={() => move(-step)}
      />
      <span className="stepper__value">{value}</span>
      <IconButton
        icon="plus"
        label={increaseLabel}
        tabIndex={-1}
        disabled={value >= max}
        onClick={() => move(step)}
      />
    </div>
  )
}
