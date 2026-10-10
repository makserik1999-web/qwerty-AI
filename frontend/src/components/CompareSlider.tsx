import { useCallback, useEffect, useRef, useState } from 'react'
import { usePrefersReducedMotion } from './anim/AnimationPlayer'
import { SceneStage } from './anim/SceneStage'
import { useI18n } from '../lib/i18n'
import type { SceneId } from '../lib/types'
import { clamp } from '../lib/utils'
import { Icon } from './ui'

interface CompareSliderProps {
  scene: SceneId
  sceneTitle: string
  textTitle: string
  textBody: string
  /** Starting reveal position, in percent. */
  initial?: number
}

const STEP = 2
const BIG_STEP = 10

/**
 * Drag-to-compare: dense textbook text on the left, the generated animation on
 * the right, split by a draggable handle. Any position is valid — the reveal is
 * continuous, never a toggle. Operable with mouse, touch and the keyboard.
 */
export function CompareSlider({
  scene,
  sceneTitle,
  textTitle,
  textBody,
  initial = 72,
}: CompareSliderProps) {
  const { t } = useI18n()
  const reducedMotion = usePrefersReducedMotion()
  const containerRef = useRef<HTMLDivElement>(null)
  const [value, setValue] = useState(initial)
  const [touched, setTouched] = useState(false)
  const [progress, setProgress] = useState(0.55)
  const frameRef = useRef<number>()

  /* The animation keeps playing regardless of how much of it is revealed. */
  useEffect(() => {
    if (reducedMotion) {
      setProgress(0.86)
      return
    }
    let start: number | undefined
    function step(now: number) {
      start ??= now
      setProgress(((now - start) / 9000) % 1)
      frameRef.current = requestAnimationFrame(step)
    }
    frameRef.current = requestAnimationFrame(step)
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
    }
  }, [reducedMotion])

  const setFromClientX = useCallback((clientX: number) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0) return
    setValue(clamp(((clientX - rect.left) / rect.width) * 100, 0, 100))
    setTouched(true)
  }, [])

  function onPointerDown(event: React.PointerEvent) {
    event.currentTarget.setPointerCapture(event.pointerId)
    setFromClientX(event.clientX)
  }

  function onPointerMove(event: React.PointerEvent) {
    if (event.buttons === 0) return
    setFromClientX(event.clientX)
  }

  function onKeyDown(event: React.KeyboardEvent) {
    const step = event.shiftKey ? BIG_STEP : STEP
    // Held keys can repeat faster than React re-renders, so each press is
    // applied to the latest value rather than the one captured in this render.
    let move: (current: number) => number
    switch (event.key) {
      case 'ArrowLeft':
      case 'ArrowDown':
        move = (current) => current - step
        break
      case 'ArrowRight':
      case 'ArrowUp':
        move = (current) => current + step
        break
      case 'PageDown':
        move = (current) => current - BIG_STEP
        break
      case 'PageUp':
        move = (current) => current + BIG_STEP
        break
      case 'Home':
        move = () => 0
        break
      case 'End':
        move = () => 100
        break
      default:
        return
    }
    event.preventDefault()
    setValue((current) => clamp(move(current), 0, 100))
    setTouched(true)
  }

  const rounded = Math.round(value)

  return (
    <div
      className="compare"
      ref={containerRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
    >
      <div className="compare__layer">
        {/* Animation sits underneath and is revealed on the right of the handle. */}
        <div className="compare__pane" style={{ clipPath: `inset(0 0 0 ${rounded}%)` }}>
          <SceneStage scene={scene} progress={progress} title={sceneTitle} />
        </div>

        <div
          className="compare__pane"
          style={{ clipPath: `inset(0 ${100 - rounded}% 0 0)` }}
          aria-hidden={rounded < 4}
        >
          <div className="compare__text">
            <h3 className="compare__text-title">{textTitle}</h3>
            <p className="compare__text-body">{textBody}</p>
          </div>
        </div>
      </div>

      <span className="compare__tag compare__tag--left">
        {t('landing.compare.textLabel')}
      </span>
      <span className="compare__tag compare__tag--right">
        {t('landing.compare.videoLabel')}
      </span>

      <button
        type="button"
        className="compare__handle"
        style={{ left: `${rounded}%` }}
        role="slider"
        aria-label={t('landing.compare.sliderLabel')}
        aria-orientation="horizontal"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={rounded}
        aria-valuetext={`${rounded}% ${t('landing.compare.textLabel')}, ${
          100 - rounded
        }% ${t('landing.compare.videoLabel')}`}
        onKeyDown={onKeyDown}
      >
        <span className="compare__grip" aria-hidden="true">
          <Icon name="chevronLeft" size={14} />
          <Icon name="chevronRight" size={14} />
        </span>
      </button>

      {touched ? null : (
        <span className="compare__hint" aria-hidden="true">
          <Icon name="sliders" size={14} />
          {t('landing.compare.hint')}
        </span>
      )}
    </div>
  )
}
