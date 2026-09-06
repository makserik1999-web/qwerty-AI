import { cx } from '../../lib/utils'

interface SkeletonProps {
  width?: string
  height?: string
  radius?: 'sm' | 'md' | 'lg' | 'full'
  className?: string
}

/**
 * Decorative placeholder. The surrounding region should carry aria-busy and a
 * live-region message so the wait is announced once, not per placeholder.
 */
export function Skeleton({
  width,
  height = '16px',
  radius = 'sm',
  className,
}: SkeletonProps) {
  return (
    <span
      aria-hidden="true"
      className={cx('skeleton', className)}
      style={{
        display: 'block',
        width: width ?? '100%',
        height,
        borderRadius: `var(--radius-${radius})`,
      }}
    />
  )
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <span className="stack stack-sm" style={{ display: 'flex' }}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          width={index === lines - 1 ? '60%' : '100%'}
          height="12px"
        />
      ))}
    </span>
  )
}
