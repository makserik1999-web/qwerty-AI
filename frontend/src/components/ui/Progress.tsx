interface ProgressBarProps {
  value: number
  label: string
}

/** Determinate progress bar (0–100). */
export function ProgressBar({ value, label }: ProgressBarProps) {
  const clamped = Math.round(Math.min(100, Math.max(0, value)))
  return (
    <div
      className="progress"
      role="progressbar"
      aria-label={label}
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="progress__bar" style={{ width: `${clamped}%` }} />
    </div>
  )
}
