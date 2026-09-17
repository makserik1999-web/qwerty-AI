import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../lib/i18n'
import type { SceneId } from '../../lib/types'
import { cx, formatClock } from '../../lib/utils'
import { Icon, IconButton } from '../ui'
import { SceneStage } from './SceneStage'
import { SCENE_TITLES } from './scenes'

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setReduced(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return reduced
}

interface AnimationPlayerProps {
  scene: SceneId
  /** Length of the rendered animation, in seconds. */
  duration: number
  title: string
  autoPlay?: boolean
  className?: string
}

/**
 * Player for a generated animation. Playback is driven by requestAnimationFrame
 * and the scene is redrawn from the current time, so scrubbing is exact.
 */
export function AnimationPlayer({
  scene,
  duration,
  title,
  autoPlay = false,
  className,
}: AnimationPlayerProps) {
  const { t } = useI18n()
  const reducedMotion = usePrefersReducedMotion()
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(autoPlay && !reducedMotion)
  const frameRef = useRef<number>()
  const lastRef = useRef<number>()

  useEffect(() => {
    setTime(0)
    setPlaying(autoPlay && !reducedMotion)
  }, [scene, autoPlay, reducedMotion])

  useEffect(() => {
    if (!playing) {
      lastRef.current = undefined
      return
    }
    function step(now: number) {
      const last = lastRef.current ?? now
      lastRef.current = now
      setTime((prev) => {
        const next = prev + (now - last) / 1000
        if (next >= duration) {
          setPlaying(false)
          return duration
        }
        return next
      })
      frameRef.current = requestAnimationFrame(step)
    }
    frameRef.current = requestAnimationFrame(step)
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
    }
  }, [playing, duration])

  const atEnd = time >= duration - 0.01

  const toggle = useCallback(() => {
    if (atEnd) {
      setTime(0)
      setPlaying(true)
      return
    }
    setPlaying((prev) => !prev)
  }, [atEnd])

  const progress = duration === 0 ? 0 : Math.min(1, time / duration)

  return (
    <figure className={cx('player', className)}>
      <div className="player__stage">
        <SceneStage scene={scene} progress={progress} title={title} />
        <span className="player__badge">{SCENE_TITLES[scene]}</span>
      </div>

      <div className="player__controls">
        <IconButton
          icon={atEnd ? 'replay' : playing ? 'pause' : 'play'}
          label={
            atEnd ? t('player.replay') : playing ? t('player.pause') : t('player.play')
          }
          variant="secondary"
          onClick={toggle}
        />
        <span className="player__time mono">
          {formatClock(time)} / {formatClock(duration)}
        </span>
        <label className="player__seek">
          <span className="visually-hidden">{t('player.seek')}</span>
          <input
            type="range"
            min={0}
            max={duration}
            step={0.1}
            value={Number(time.toFixed(1))}
            onChange={(event) => {
              setPlaying(false)
              setTime(Number(event.target.value))
            }}
          />
        </label>
      </div>

      {reducedMotion ? (
        <figcaption className="player__note">
          <Icon name="info" size={15} />
          {t('player.reducedMotion')}
        </figcaption>
      ) : null}
    </figure>
  )
}

/**
 * Compact autoplaying preview used on cards. Plays on hover or keyboard focus
 * and otherwise shows a still poster frame.
 */
export function ScenePreview({
  scene,
  title,
  poster = 0.92,
  className,
}: {
  scene: SceneId
  title: string
  poster?: number
  className?: string
}) {
  const reducedMotion = usePrefersReducedMotion()
  const [active, setActive] = useState(false)
  const [progress, setProgress] = useState(poster)
  const frameRef = useRef<number>()

  useEffect(() => {
    if (!active || reducedMotion) {
      setProgress(poster)
      return
    }
    let start: number | undefined
    function step(now: number) {
      start ??= now
      const value = ((now - start) / 6000) % 1
      setProgress(value)
      frameRef.current = requestAnimationFrame(step)
    }
    frameRef.current = requestAnimationFrame(step)
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
    }
  }, [active, poster, reducedMotion])

  return (
    <div
      className={cx('scene-preview', className)}
      onMouseEnter={() => setActive(true)}
      onMouseLeave={() => setActive(false)}
      onFocus={() => setActive(true)}
      onBlur={() => setActive(false)}
    >
      <SceneStage scene={scene} progress={progress} title={title} />
    </div>
  )
}
