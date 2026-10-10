/** Small maths helpers shared by every animation scene. */

export const VIEW_W = 640
export const VIEW_H = 400

export function lerp(from: number, to: number, t: number): number {
  return from + (to - from) * t
}

/**
 * Progress of one phase of a scene. Returns 0 before `start`, 1 after `end`,
 * and an eased value in between.
 */
export function phase(p: number, start: number, end: number): number {
  if (p <= start) return 0
  if (p >= end) return 1
  return (p - start) / (end - start)
}

/** Standard ease used across the product: cubic-bezier(.4,0,.2,1) approximated. */
export function ease(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

export function easeOut(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

export function eased(p: number, start: number, end: number): number {
  return ease(phase(p, start, end))
}

/** Opacity helper for elements that fade in and stay. */
export function appear(p: number, start: number, length = 0.06): number {
  return phase(p, start, start + length)
}

export function polygon(points: Array<[number, number]>): string {
  return points.map(([x, y]) => `${round(x)},${round(y)}`).join(' ')
}

export function round(value: number): number {
  return Math.round(value * 100) / 100
}
