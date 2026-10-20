import { useI18n } from '../lib/i18n'
import type { Orientation } from '../lib/live'
import { Icon } from './ui'

/**
 * Which way up the next video is: landscape for the classroom screen, portrait
 * (9:16) for a phone - a WhatsApp status, a class chat, a Reels-style post.
 *
 * Beside the length for the same reason the length is beside the voice: it
 * changes the video that gets made. The scene is laid out for the frame it is
 * rendered in, so this is not a crop of the landscape video - a portrait one
 * stacks its parts top to bottom instead of left to right.
 *
 * Shares the length control's look (.length), so the row reads as one set of
 * choices about the video.
 */

export const ORIENTATIONS: readonly Orientation[] = ['landscape', 'portrait']

interface OrientationPickerProps {
  value: Orientation
  onChange: (value: Orientation) => void
  /** Greyed out while a video is being made - it is already being made this way. */
  disabled?: boolean
}

export function OrientationPicker({ value, onChange, disabled = false }: OrientationPickerProps) {
  const { t } = useI18n()

  return (
    <div className="length" data-testid="orientation-controls">
      <span className="length__label">
        <Icon name="sliders" size={15} />
        <span>{t('orientation.label')}</span>
      </span>

      <div className="length__options" role="radiogroup" aria-label={t('orientation.label')}>
        {ORIENTATIONS.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={value === option}
            aria-label={`${t(`orientation.${option}` as 'orientation.landscape')} — ${t(
              `orientation.${option}.hint` as 'orientation.landscape.hint',
            )}`}
            title={t(`orientation.${option}.hint` as 'orientation.landscape.hint')}
            data-testid={`orientation-${option}`}
            disabled={disabled}
            onClick={() => onChange(option)}
            className={value === option ? 'length__option is-active' : 'length__option'}
          >
            <span className="length__name">
              {t(`orientation.${option}` as 'orientation.landscape')}
            </span>
            <span className="length__hint">
              {t(`orientation.${option}.hint` as 'orientation.landscape.hint')}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
