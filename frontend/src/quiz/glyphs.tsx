/**
 * The four answer marks.
 *
 * Every option carries a shape as well as a colour, so a student who cannot
 * tell the clay from the green still has something to go by - and "the moon
 * one" is easier to say across a classroom than "option C".
 *
 * The shapes are borrowed from Kazakh ornament rather than from geometry
 * class: the шаңырақ seen from below, the crescent, the nested rhombus of a
 * текемет, and the ram's horn - қошқар мүйіз - that runs through almost every
 * pattern in the country. Four silhouettes that stay distinct at 16 pixels.
 */

export const MARKS = ['shanyrak', 'ai', 'romb', 'muiz'] as const
export type Mark = (typeof MARKS)[number]

const PATHS: Record<Mark, React.ReactNode> = {
  shanyrak: (
    <>
      <circle cx="12" cy="12" r="4.4" />
      <path d="M12 7.6v8.8M7.6 12h8.8M19 12h2.6M16.95 16.95l1.84 1.84M12 19v2.6M7.05 16.95l-1.84 1.84M5 12H2.4M7.05 7.05 5.21 5.21M12 5V2.4M16.95 7.05l1.84-1.84" />
    </>
  ),
  ai: <path d="M15.8 4.3A8.6 8.6 0 1 0 15.8 19.7 6.6 6.6 0 1 1 15.8 4.3Z" />,
  romb: (
    <>
      <path d="M12 3 21 12 12 21 3 12Z" />
      <path d="M12 8.4 15.6 12 12 15.6 8.4 12Z" />
    </>
  ),
  muiz: (
    <path d="M12 20.5v-8M12 12.5c0-4.3-2.4-7-5.4-7-2.2 0-3.4 1.7-3.4 3.4 0 1.7 1.3 2.9 2.8 2.9 1.3 0 2.2-.9 2.2-2.1 0-1-.7-1.7-1.6-1.7M12 12.5c0-4.3 2.4-7 5.4-7 2.2 0 3.4 1.7 3.4 3.4 0 1.7-1.3 2.9-2.8 2.9-1.3 0-2.2-.9-2.2-2.1 0-1 .7-1.7 1.6-1.7" />
  ),
}

export function markOf(index: number): Mark {
  return MARKS[((index % MARKS.length) + MARKS.length) % MARKS.length]
}

export function Glyph({
  index,
  size = 24,
  className,
}: {
  index: number
  size?: number
  className?: string
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {PATHS[markOf(index)]}
    </svg>
  )
}

/** A letter for screen readers and for the teacher's tables. */
export function letterOf(index: number): string {
  return 'ABCD'[index] ?? String(index + 1)
}
