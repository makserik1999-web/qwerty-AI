import { useEffect, useState } from 'react'
import { getProviders } from './api'

type Providers = { google: boolean; phone: boolean }

const NONE: Providers = { google: false, phone: false }

// Asked once per page load: what the server has set up does not change while
// a tab is open, and every sign-in screen wants the same answer.
let pending: Promise<Providers> | null = null

function load(): Promise<Providers> {
  if (!pending) {
    pending = getProviders().catch(() => {
      pending = null // try again next time rather than remembering a failure
      return NONE
    })
  }
  return pending
}

/** Which sign-in and confirmation methods are on. Off until the server says. */
export function useProviders(): Providers {
  const [providers, setProviders] = useState<Providers>(NONE)
  useEffect(() => {
    let active = true
    void load().then((found) => {
      if (active) setProviders(found)
    })
    return () => {
      active = false
    }
  }, [])
  return providers
}
