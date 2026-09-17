import { useI18n } from '../../lib/i18n'
import { cx, formatClock } from '../../lib/utils'
import { Icon, IconButton } from '../ui'
import { hasUsableDuration, useVideoPlayer } from './useVideoPlayer'

/**
 * The rendered answer, playing.
 *
 * This replaces AnimationPlayer for real explanations. The prototype's player
 * drew one of seven built-in SVG scenes and recomputed the geometry on every
 * frame; what the agent actually produces is an mp4 that Manim rendered for
 * this specific question, so there is a file to play rather than a scene to
 * choose. The seven scenes stay on the landing page, where they are honest -
 * they run with no server at all.
 *
 * The chrome is deliberately the same markup as AnimationPlayer's, so both
 * read as one control and the styling in anim.css covers both.
 *
 * Playback state comes from useVideoPlayer, carried over from the old
 * interface along with the bug it documents: a scrub flag that used to strand
 * itself and freeze the bar while the video kept playing.
 */

interface VideoPlayerProps {
  /** Served from /media, behind the session cookie. */
  src: string
  title: string
  autoPlay?: boolean
  className?: string
}

export function VideoPlayer({ src, title, autoPlay = false, className }: VideoPlayerProps) {
  const { t } = useI18n()
  const {
    videoRef,
    isPaused,
    currentTime,
    duration,
    buffered,
    isLoaded,
    hasError,
    isWaiting,
    togglePlay,
    seekTo,
    setScrubbing,
  } = useVideoPlayer(src)

  const known = hasUsableDuration(duration)
  const atEnd = known && currentTime >= duration - 0.05

  if (hasError) {
    return (
      <div className={cx('player player--failed', className)} role="alert">
        <Icon name="alert" size={18} />
        <p className="text-sm">{t('player.failed')}</p>
      </div>
    )
  }

  return (
    <figure className={cx('player', className)}>
      <div className="player__stage">
        <video
          ref={videoRef}
          className="player__video"
          src={src}
          title={title}
          autoPlay={autoPlay}
          playsInline
          preload="metadata"
          onClick={togglePlay}
        />
        {isWaiting || !isLoaded ? (
          <div className="player__waiting" role="status" aria-live="polite">
            <span className="visually-hidden">{t('common.loading')}</span>
          </div>
        ) : null}
      </div>

      <div className="player__controls">
        <IconButton
          icon={atEnd ? 'replay' : isPaused ? 'play' : 'pause'}
          label={atEnd ? t('player.replay') : isPaused ? t('player.play') : t('player.pause')}
          variant="secondary"
          onClick={togglePlay}
        />
        <span className="player__time mono">
          {formatClock(currentTime)} / {formatClock(known ? duration : 0)}
        </span>
        <label className="player__seek">
          <span className="visually-hidden">{t('player.seek')}</span>
          {/* The buffered width is painted behind the track, so the loading
              state is visible on a video that is still arriving. */}
          <span
            className="player__buffered"
            style={{ width: known ? `${Math.min(100, (buffered / duration) * 100)}%` : '0%' }}
            aria-hidden="true"
          />
          <input
            type="range"
            min={0}
            max={known ? duration : 0}
            step={0.1}
            value={Number(currentTime.toFixed(1))}
            disabled={!known}
            onPointerDown={() => setScrubbing(true)}
            onPointerUp={() => setScrubbing(false)}
            onBlur={() => setScrubbing(false)}
            onChange={(event) => seekTo(Number(event.target.value))}
          />
        </label>
        <a
          className="player__download"
          href={src}
          download
          title={t('player.download')}
          aria-label={t('player.download')}
        >
          <Icon name="download" size={16} />
        </a>
      </div>
    </figure>
  )
}
