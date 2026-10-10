import React from 'react';

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
 */

export type NarrationVoice = 'aigul' | 'daulet';

interface NarrationToggleProps {
  enabled: boolean;
  voice: NarrationVoice;
  onEnabledChange: (enabled: boolean) => void;
  onVoiceChange: (voice: NarrationVoice) => void;
  /** Greyed out while a video is being made - it is already being made this way. */
  disabled?: boolean;
}

const VOICES: ReadonlyArray<{ id: NarrationVoice; label: string; title: string }> = [
  { id: 'aigul', label: 'Айгүл', title: 'Әйел дауысы / женский голос' },
  { id: 'daulet', label: 'Дәулет', title: 'Ер дауысы / мужской голос' },
];

export const NarrationToggle: React.FC<NarrationToggleProps> = ({
  enabled,
  voice,
  onEnabledChange,
  onVoiceChange,
  disabled = false,
}) => (
  <div className="flex items-center gap-2" data-testid="narration-controls">
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={enabled ? 'Отключить озвучку' : 'Включить озвучку'}
      title={
        enabled
          ? 'Видео с голосом - примерно минута'
          : 'Без голоса - короче, только подписи'
      }
      data-testid="narration-toggle"
      disabled={disabled}
      onClick={() => onEnabledChange(!enabled)}
      className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border transition-colors
                  duration-150 ${
                    disabled
                      ? 'border-dark-600 text-gray-600 cursor-not-allowed'
                      : enabled
                        ? 'border-accent-primary/60 text-accent-primary hover:bg-dark-700'
                        : 'border-dark-500 text-gray-500 hover:bg-dark-700'
                  }`}
    >
      {enabled ? (
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15.536 8.464a5 5 0 010 7.072M12 6L8 10H5v4h3l4 4V6z"
          />
        </svg>
      ) : (
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 6L8 10H5v4h3l4 4V6zM17 9l4 6m0-6l-4 6"
          />
        </svg>
      )}
      <span>Дауыс</span>
    </button>

    {/* Hidden rather than disabled when off: a voice picker for a video that
        will not speak is a control with nothing to control. */}
    {enabled && (
      <div className="flex items-center gap-1" role="radiogroup" aria-label="Голос">
        {VOICES.map((option) => (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={voice === option.id}
            title={option.title}
            data-testid={`voice-${option.id}`}
            disabled={disabled}
            onClick={() => onVoiceChange(option.id)}
            className={`px-2 py-1 rounded-lg transition-colors duration-150 ${
              disabled
                ? 'text-gray-600 cursor-not-allowed'
                : voice === option.id
                  ? 'bg-accent-primary/15 text-accent-primary'
                  : 'text-gray-500 hover:bg-dark-700'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    )}
  </div>
);
