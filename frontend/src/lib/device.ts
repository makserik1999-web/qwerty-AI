/**
 * A random id for this browser, and the invite code a visitor arrived with.
 *
 * The id is only ever sent at sign-up and sign-in, where the server stores a
 * keyed hash of it: enough to notice many accounts made in one browser (trial
 * farming, inviting yourself), not enough to know whose browser it is.
 * Storage can be unavailable (private mode, blocked site data) - then there is
 * simply no id, and nothing breaks.
 */

const DEVICE_KEY = 'akron.device.v1'
const REF_KEY = 'akron.ref.v1'

function store(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function deviceId(): string {
  const s = store()
  try {
    const found = s?.getItem(DEVICE_KEY)
    if (found) return found
    const made =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
    s?.setItem(DEVICE_KEY, made)
    return made
  } catch {
    return ''
  }
}

/** Remember ?ref= from an invite link until the visitor signs up. */
export function rememberRef(ref: string | null): void {
  const code = (ref ?? '').trim().toUpperCase().slice(0, 12)
  if (!code) return
  try {
    store()?.setItem(REF_KEY, code)
  } catch {
    /* without storage the code still works on the page it arrived on */
  }
}

export function inviteRef(): string {
  try {
    return store()?.getItem(REF_KEY) ?? ''
  } catch {
    return ''
  }
}
