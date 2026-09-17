/**
 * The real backend, in place of `mockApi`'s account handling.
 *
 * Identity lives in an HttpOnly session cookie the browser sends on its own,
 * so nothing here passes a user id or a token: every request is `credentials:
 * 'include'` and the server works out who is asking. That also means a signed
 * -in person is signed in in every tab, and signing out ends all of them.
 *
 * Errors come back as an `ApiError` carrying the status, because the caller
 * usually wants to say something different for "wrong password" than for
 * "that address is taken" - and it should say it in the reader's language,
 * which the server does not know. `detail` is kept for the cases nothing has
 * been translated for yet.
 */
import type { Role } from './types'

/** What /api/auth/* returns. `username` is derived server-side from the email. */
export interface ApiUser {
  id: string
  username: string
  email: string | null
  name: string
  role: Role
  created_at: string | null
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail || `Request failed (${status})`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Status 0 means the request never arrived - offline, or the server is down. */
export const NETWORK_ERROR = 0

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
      ...init,
    })
  } catch {
    throw new ApiError(NETWORK_ERROR, '')
  }

  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      /* a non-JSON error body tells us nothing useful; the status carries it */
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export interface SignUpInput {
  name: string
  email: string
  password: string
  role: Role
}

export async function signUp(input: SignUpInput): Promise<ApiUser> {
  const { user } = await request<{ user: ApiUser }>('/auth/signup', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return user
}

export async function signIn(input: { email: string; password: string }): Promise<ApiUser> {
  const { user } = await request<{ user: ApiUser }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return user
}

export async function signOut(): Promise<void> {
  await request('/auth/logout', { method: 'POST' })
}

/**
 * Who the cookie belongs to, or null when it belongs to nobody.
 *
 * A missing session is the ordinary state for a first visit, so 401 is not
 * treated as a failure here. Anything else is - a server that is down must
 * not look the same as a signed-out visitor, or a blip would sign everyone
 * out and lose whatever they were in the middle of.
 */
export async function currentUser(): Promise<ApiUser | null> {
  try {
    const { user } = await request<{ user: ApiUser }>('/auth/me')
    return user
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

export async function updateProfile(input: {
  name?: string
  email?: string
}): Promise<ApiUser> {
  const { user } = await request<{ user: ApiUser }>('/auth/profile', {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  return user
}

export async function deleteAccount(): Promise<void> {
  await request('/auth/account', { method: 'DELETE' })
}
