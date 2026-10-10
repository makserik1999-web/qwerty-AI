/**
 * Turning a failed request into something worth reading.
 *
 * The server answers in English, because it does not know who is asking or in
 * which of the three interface languages. So the status is what gets
 * translated, and the server's own `detail` is only shown when it is more
 * specific than anything we have a string for - a validation message naming
 * the field, say. That way nothing is ever silently swallowed, but the common
 * cases read like the rest of the interface.
 */
import { ApiError, NETWORK_ERROR } from './api'
import type { StringKey } from './strings'

export interface AuthFailure {
  key: StringKey
  /** Shown instead of the translation when the server said something specific. */
  detail?: string
}

/**
 * @param invalidKey what a 401 means here - "wrong password" on the sign-in
 *   screen, but a signed-out session anywhere else.
 */
export function describeAuthError(error: unknown, invalidKey: StringKey): AuthFailure {
  if (!(error instanceof ApiError)) return { key: 'auth.error.unknown' }

  switch (error.status) {
    case NETWORK_ERROR:
      return { key: 'auth.error.network' }
    case 401:
      return { key: invalidKey }
    case 409:
      return { key: 'auth.error.emailTaken' }
    case 429:
      return { key: 'auth.error.tooMany' }
    case 400:
      // Client-side validation catches these first, so a 400 arriving here
      // means the two disagree - and the server's wording is the useful half.
      return { key: 'auth.error.unknown', detail: error.detail || undefined }
    default:
      return { key: 'auth.error.unknown' }
  }
}
