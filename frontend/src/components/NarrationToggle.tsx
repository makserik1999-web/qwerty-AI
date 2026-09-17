import { useI18n } from '../lib/i18n'
import { Icon } from './ui'

/**
 * Whether the next video speaks, and in whose voice.
 *
 * It sits by the composer rather than in a settings screen because it changes
 * what the answer *is*, not how the app behaves: with the voice on the video
 * runs about a minute and explains itself aloud, with it off it is a silent
 * half-minute of captions. That is a choice worth making per question, and
 * one people should see before they ask rather than discover afterwards.
 *
 * The two names are the Kazakh voices, which are the ones anyone here can
 * judge. Russian and English answers follow the same choice with a voice of
 * the same gender.
 *
 * Carried over from the old interface and re-dressed: the original was
 * written in Tailwind classes against a palette that no longer exists.
 */

export type NarrationVoice = 'aigul' | 'daulet'

export const NARRATION_VOICES: readonly NarrationVoice[] = ['aigul', 'daulet']

interface NarrationToggleProps {
  enabled: boolean
  voice: NarrationVoice
  onEnabledChange: (enabled: boolean) => void
  onVoiceChange: (voice: NarrationVoice) => void
  /** Greyed out while a video is being made - it is already being made this way. */
  disabled?: boolean
}

export function NarrationToggle({
  enabled,
  voice,
  onEnabledChange,
  onVoiceChange,
  disabled = false,
}: NarrationToggleProps) {
  const { t } = useI18n()

  return (
    <div className="narration" data-testid="narration-controls">
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={enabled ? t('narration.disable') : t('narration.enable')}
        title={enabled ? t('narration.on') : t('narration.off')}
        data-testid="narration-toggle"
        disabled={disabled}
        onClick={() => onEnabledChange(!enabled)}
        className={enabled ? 'narration__switch is-on' : 'narration__switch'}
      >
        <Icon name={enabled ? 'volumeOn' : 'volumeOff'} size={15} />
        <span>{t('narration.label')}</span>
      </button>

      {/* Hidden rather than disabled when off: a voice picker for a video that
          will not speak is a control with nothing to control. */}
      {enabled ? (
        <div className="narration__voices" role="radiogroup" aria-label={t('narration.voiceLabel')}>
          {NARRATION_VOICES.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={voice === option}
              data-testid={`voice-${option}`}
              disabled={disabled}
              onClick={() => onVoiceChange(option)}
              className={
                voice === option ? 'narration__voice is-active' : 'narration__voice'
              }
            >
              {t(`narration.voice.${option}` as 'narration.voice.aigul')}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
