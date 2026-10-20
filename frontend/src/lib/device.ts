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

/* An invite is for the next account made in this browser, soon. It used to be
   kept for good: whoever signed up on that computer months later - a tester
   on the owner's laptop - was told a colleague had invited them. Now it lasts
   REF_TTL_DAYS and goes as soon as any account signs in or up here. */
const REF_TTL_DAYS = 30
let refInMemory = ''

/** Remember ?ref= from an invite link until the visitor signs up. */
export function rememberRef(ref: string | null): void {
  const code = (ref ?? '').trim().toUpperCase().slice(0, 12)
  if (!code) return
  refInMemory = code
  try {
    store()?.setItem(REF_KEY, JSON.stringify({ code, at: Date.now() }))
  } catch {
    /* without storage the code still works on the page it arrived on */
  }
}

export function inviteRef(): string {
  try {
    const raw = store()?.getItem(REF_KEY)
    if (!raw) return refInMemory
    const saved = JSON.parse(raw) as { code?: unknown; at?: unknown }
    const fresh =
      typeof saved.code === 'string' &&
      typeof saved.at === 'number' &&
      Date.now() - saved.at < REF_TTL_DAYS * 24 * 3600 * 1000
    if (fresh) return saved.code as string
  } catch {
    /* a bare code from before the date was kept: too old to trust */
  }
  forgetRef()
  return refInMemory
}

/** The invite has been used, or an account already lives in this browser. */
export function forgetRef(): void {
  refInMemory = ''
  try {
    store()?.removeItem(REF_KEY)
  } catch {
    /* nothing stored, nothing to forget */
  }
}
