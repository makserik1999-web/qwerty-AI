import { cx } from '../../lib/utils'
import { Icon } from './Icon'
import { Spinner } from './Spinner'

export interface ProgressStep {
  key: string
  label: string
}

interface ProgressStepsProps {
  steps: ProgressStep[]
  /** Index of the step currently running. */
  activeIndex: number
}

/** Named stages for a long-running job, so waiting never feels frozen. */
export function ProgressSteps({ steps, activeIndex }: ProgressStepsProps) {
  return (
    <ol className="progress-steps">
      {steps.map((step, index) => {
        const done = index < activeIndex
        const active = index === activeIndex
        return (
          <li
            key={step.key}
            className={cx(
              'progress-steps__item',
              done && 'is-done',
              active && 'is-active',
            )}
          >
            <span className="progress-steps__marker">
              {done ? (
                <Icon name="check" size={14} />
              ) : active ? (
                <Spinner />
              ) : (
                <span className="visually-hidden">{index + 1}</span>
              )}
            </span>
            <span>{step.label}</span>
          </li>
        )
      })}
    </ol>
  )
}
