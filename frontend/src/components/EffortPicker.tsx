import { useI18n } from '../lib/i18n'
import type { Effort } from '../lib/live'
import { Icon } from './ui'

/**
 * How much is spent making the video.
 *
 * WHAT IT ACTUALLY CHANGES, and why the label says "quality" rather than
 * "effort". The visible difference is the picture: manim renders at 480p15,
 * 720p30 or 1080p60, and that is frames as well as pixels - at the low
 * profile the animation runs at fifteen frames a second, which is visibly
 * choppy on a projector. Behind it, a higher level also buys more attempts to
 * get a difficult animation to render at all. "Effort" is what it costs us;
 * "quality" is what the teacher is choosing, and a control should be named
 * for the second.
 *
 * WHAT IT DELIBERATELY DOES NOT CHANGE: how hard the model thinks about the
 * Manim script. Measured - at the default reasoning effort the script
 * rendered 2 times out of 4, at "low" it rendered 4 of 4, because the extra
 * deliberation goes into inventing API that is not in the prompt. A control
 * whose top setting broke rendering would be selling a downgrade.
 *
 * The waiting time is shown because it is the real price. Measured on one
 * 37-second scene: 11.4 seconds to render at the low profile against 68.8 at
 * the high one. On a long video that is the difference between about half a
 * minute and about three minutes, and a wait nobody warned about is the kind
 * people are angry at rather than patient with.
 */

export const EFFORT_LEVELS: readonly Effort[] = ['low', 'medium', 'high']

interface EffortPickerProps {
  value: Effort
  onChange: (value: Effort) => void
  /** Greyed out while a video is being made - it is already being made this way. */
  disabled?: boolean
}

export function EffortPicker({ value, onChange, disabled = false }: EffortPickerProps) {
  const { t } = useI18n()

  return (
    <div className="length" data-testid="effort-controls">
      <span className="length__label">
        <Icon name="sparkle" size={15} />
        <span>{t('effort.label')}</span>
      </span>

      <div className="length__options" role="radiogroup" aria-label={t('effort.label')}>
        {EFFORT_LEVELS.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={value === option}
            /* The resolution and the wait belong in the accessible name too:
               a screen reader announcing only "high" would hide both the
               thing being bought and the thing being paid. */
            aria-label={`${t(`effort.${option}` as 'effort.low')} — ${t(
              `effort.${option}.hint` as 'effort.low.hint',
            )}, ${t(`effort.${option}.wait` as 'effort.low.wait')}`}
            title={t(`effort.${option}.wait` as 'effort.low.wait')}
            data-testid={`effort-${option}`}
            disabled={disabled}
            onClick={() => onChange(option)}
            className={value === option ? 'length__option is-active' : 'length__option'}
          >
            <span className="length__name">{t(`effort.${option}` as 'effort.low')}</span>
            <span className="length__hint">
              {t(`effort.${option}.hint` as 'effort.low.hint')}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
