import type { SceneId } from '../../lib/types'
import { cx } from '../../lib/utils'
import { VIEW_H, VIEW_W } from './helpers'
import { SCENES } from './scenes'

interface SceneStageProps {
  scene: SceneId
  /** Playback position, 0 → 1. */
  progress: number
  title: string
  className?: string
}

/**
 * The animation surface itself: a single SVG whose contents are a pure
 * function of `progress`. Nothing here is a static image — every frame is
 * computed from the scene's geometry.
 */
export function SceneStage({ scene, progress, title, className }: SceneStageProps) {
  const Scene = SCENES[scene]
  return (
    <svg
      className={cx('scene', className)}
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      role="img"
      aria-label={title}
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <marker
          id="anyq-arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M0,1 L9,5 L0,9 z" fill="currentColor" />
        </marker>
      </defs>
      <rect className="scene__bg" x={0} y={0} width={VIEW_W} height={VIEW_H} />
      <Scene p={progress} />
    </svg>
  )
}
