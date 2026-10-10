import { useI18n } from '../lib/i18n'
import type { VideoLength } from '../lib/live'
import { Icon } from './ui'

/**
 * How long the next video runs.
 *
 * It sits beside the narration toggle, and for the same reason: it changes
 * what the answer *is*, not how the app behaves. A teacher fitting an
 * explanation into the last five minutes of a lesson wants a different video
 * from one setting homework, and that is a decision per question.
 *
 * WHY THREE BUTTONS AND NOT A SLIDER OF SECONDS. Nothing in the pipeline
 * takes a duration. A video lasts exactly as long as its animations, and with
 * narration on those are pinned to the speech, so the length is set by how
 * much the script is told to say. Characters convert to seconds at a rate
 * that was measured rather than assumed - fourteen renders gave 11.8 to
 * 13.8 characters per second, a spread of about eight percent. A control promising
 * "35 seconds" would be promising a precision that does not exist; "~30-40
 * sec" is the truth, and buckets are the honest shape for it.
 *
 * The times are shown, not just the names. "Medium" alone tells nobody
 * anything, and the whole point of the control is choosing a duration.
 */

export const VIDEO_LENGTHS: readonly VideoLength[] = ['short', 'medium', 'long']

interface VideoLengthPickerProps {
  value: VideoLength
  onChange: (value: VideoLength) => void
  /** Greyed out while a video is being made - it is already being made this way. */
  disabled?: boolean
}

export function VideoLengthPicker({
  value,
  onChange,
  disabled = false,
}: VideoLengthPickerProps) {
  const { t } = useI18n()

  return (
    <div className="length" data-testid="video-length-controls">
      <span className="length__label">
        <Icon name="sliders" size={15} />
        <span>{t('length.label')}</span>
      </span>

      <div className="length__options" role="radiogroup" aria-label={t('length.label')}>
        {VIDEO_LENGTHS.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={value === option}
            /* The approximate seconds belong in the accessible name too: a
               screen reader that announced only "short" would hide the one
               fact this control exists to convey. */
            aria-label={`${t(`length.${option}` as 'length.short')} — ${t(
              `length.${option}.hint` as 'length.short.hint',
            )}`}
            title={t(`length.${option}.hint` as 'length.short.hint')}
            data-testid={`length-${option}`}
            disabled={disabled}
            onClick={() => onChange(option)}
            className={value === option ? 'length__option is-active' : 'length__option'}
          >
            <span className="length__name">
              {t(`length.${option}` as 'length.short')}
            </span>
            <span className="length__hint">
              {t(`length.${option}.hint` as 'length.short.hint')}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
