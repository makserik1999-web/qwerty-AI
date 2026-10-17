import { useCallback, useState } from 'react'
import { useI18n } from '../../lib/i18n'
import type { UiLang } from '../../lib/types'
import { cx } from '../../lib/utils'
import { Menu } from '../ui'

/**
 * Playback speed, shared by the video and the built-in scenes.
 *
 * The steps are the ones YouTube taught everyone. The choice is remembered on
 * this device: a student who listens at 1.5x wants the next answer at 1.5x
 * too, and a teacher who slowed things down for the projector wants it slow
 * tomorrow as well.
 */
export const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const

const STORAGE_KEY = 'anyq.player.rate'

function readRate(): number {
  try {
    const value = Number(window.localStorage.getItem(STORAGE_KEY))
    return (SPEEDS as readonly number[]).includes(value) ? value : 1
  } catch {
    return 1
  }
}

export function usePlaybackRate(): [number, (rate: number) => void] {
  const [rate, setRateState] = useState(readRate)
  const setRate = useCallback((next: number) => {
    setRateState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, String(next))
    } catch {
      /* storage unavailable - the speed still applies to this video */
    }
  }, [])
  return [rate, setRate]
}

/** "1,5×" in Kazakh and Russian, "1.5×" in English. */
export function formatRate(rate: number, lang: UiLang): string {
  const digits = String(rate)
  return `${lang === 'en' ? digits : digits.replace('.', ',')}×`
}

export function SpeedMenu({ rate, onChange }: { rate: number; onChange: (rate: number) => void }) {
  const { t, lang } = useI18n()
  const current = formatRate(rate, lang)
  return (
    <div className={cx('player__speed', rate !== 1 && 'is-changed')}>
      <Menu
        label={`${t('player.speed')}: ${current}`}
        text={current}
        side="top"
        align="end"
        selectedKey={String(rate)}
        items={SPEEDS.map((value) => ({
          key: String(value),
          label: value === 1 ? t('player.speedNormal') : formatRate(value, lang),
          onSelect: () => onChange(value),
        }))}
      />
    </div>
  )
}
