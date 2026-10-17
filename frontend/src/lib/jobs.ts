/**
 * Waiting for something the server makes in the background.
 *
 * A lesson plan or a quiz draft can take two minutes, and Cloudflare closes
 * any request after 100 seconds. So the page asks with `Prefer:
 * respond-async`, gets a job id back at once, and polls here until it is
 * done. A failure comes back as the same ApiError the request itself would
 * have thrown, so the pages handle both the same way.
 */
import { ApiError } from './api'

/** The header that turns a generating request into a job. */
export const BACKGROUND: Record<string, string> = { Prefer: 'respond-async' }

export interface JobState {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'failed'
  error?: { status?: number; detail?: string; code?: string } & Record<string, unknown>
  result?: unknown
  lesson_plan?: unknown
}

const POLL_MS = 2500
// Longer than any generation is allowed to run on the server.
const GIVE_UP_MS = 6 * 60_000
// A dropped poll is not a failed job: the work goes on regardless.
const MAX_MISSES = 6

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

export async function waitForJob<T>(jobId: string, pick: (job: JobState) => T | null | undefined): Promise<T> {
  const deadline = Date.now() + GIVE_UP_MS
  let misses = 0
  while (Date.now() < deadline) {
    await sleep(POLL_MS)
    let job: JobState
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      })
      if (response.status === 401 || response.status === 404) throw new ApiError(response.status, '')
      if (!response.ok) throw new Error(String(response.status))
      job = (await response.json()) as JobState
    } catch (error) {
      if (error instanceof ApiError) throw error
      misses += 1
      if (misses >= MAX_MISSES) throw new ApiError(0, '')
      continue
    }
    misses = 0

    if (job.status === 'failed') {
      const failure = job.error ?? {}
      throw new ApiError(failure.status || 502, failure.detail || '', failure.code || '', failure)
    }
    if (job.status === 'done') {
      const value = pick(job)
      // Collected already - another tab, or a poll whose answer was lost.
      if (value === null || value === undefined) throw new ApiError(410, '')
      return value
    }
  }
  throw new ApiError(504, '')
}
