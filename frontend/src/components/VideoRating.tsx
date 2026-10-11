import { useState } from 'react'
import { rateVideo, type Rating } from '../lib/api'
import { useI18n } from '../lib/i18n'

/**
 * 👍/👎 under a topic video. The votes decide which of a topic's versions the
 * next person is shown, so they are worth one click; a second click on the
 * same thumb takes the vote back.
 */
export function VideoRating({ videoId, initial }: { videoId: string; initial?: Rating | null }) {
  const { t } = useI18n()
  const [rating, setRating] = useState<Rating | null>(initial ?? null)
  const [busy, setBusy] = useState(false)

  async function vote(value: 'up' | 'down') {
    const mine = rating?.mine ?? 0
    const next = (value === 'up' && mine === 1) || (value === 'down' && mine === -1) ? 'none' : value
    setBusy(true)
    try {
      setRating(await rateVideo(videoId, next))
    } catch {
      /* a lost vote is not worth an error on screen */
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="video-rating" role="group" aria-label={`${t('video.rateUp')} / ${t('video.rateDown')}`}>
      <button
        type="button"
        className={rating?.mine === 1 ? 'video-rating__btn is-on' : 'video-rating__btn'}
        aria-pressed={rating?.mine === 1}
        aria-label={t('video.rateUp')}
        disabled={busy}
        onClick={() => void vote('up')}
      >
        👍{rating ? <span>{rating.up}</span> : null}
      </button>
      <button
        type="button"
        className={rating?.mine === -1 ? 'video-rating__btn is-on' : 'video-rating__btn'}
        aria-pressed={rating?.mine === -1}
        aria-label={t('video.rateDown')}
        disabled={busy}
        onClick={() => void vote('down')}
      >
        👎{rating ? <span>{rating.down}</span> : null}
      </button>
    </div>
  )
}
