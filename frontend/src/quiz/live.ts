/**
 * The quiz's live channel, and the clock it runs on.
 *
 * The socket only ever tells; nothing is sent over it but a hello and pings.
 * When it drops, it reconnects and the first message after reconnecting is a
 * full snapshot - so a missed event costs a moment, never a wrong screen.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { socketUrl } from './api'

/** Close codes after which reconnecting cannot help. */
const FINAL_CODES = new Set([1008, 4400, 4401, 4403, 4410])

interface SocketOptions<E> {
  path: string
  enabled: boolean
  /** Sent first on every (re)connect - the player's token goes here. */
  hello?: Record<string, unknown>
  onEvent: (event: E) => void
  /** Called when the server closes for good (kicked, unknown token). */
  onFinal?: (code: number) => void
}

export function useQuizSocket<E extends { type: string }>({
  path,
  enabled,
  hello,
  onEvent,
  onFinal,
}: SocketOptions<E>): { connected: boolean } {
  const [connected, setConnected] = useState(false)
  const onEventRef = useRef(onEvent)
  const onFinalRef = useRef(onFinal)
  const helloRef = useRef(hello)
  onEventRef.current = onEvent
  onFinalRef.current = onFinal
  helloRef.current = hello

  useEffect(() => {
    if (!enabled) return
    let socket: WebSocket | null = null
    let ping: number | undefined
    let retry: number | undefined
    let attempt = 0
    let stopped = false

    const open = () => {
      socket = new WebSocket(socketUrl(path))
      socket.onopen = () => {
        attempt = 0
        setConnected(true)
        if (helloRef.current) socket?.send(JSON.stringify(helloRef.current))
        ping = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'ping' }))
          }
        }, 20000)
      }
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as E
          if (event && typeof event.type === 'string') onEventRef.current(event)
        } catch {
          /* not ours to understand */
        }
      }
      socket.onclose = (event) => {
        setConnected(false)
        window.clearInterval(ping)
        if (stopped) return
        if (FINAL_CODES.has(event.code)) {
          onFinalRef.current?.(event.code)
          return
        }
        attempt += 1
        const delay = Math.min(10000, 600 * 2 ** Math.min(attempt, 5))
        retry = window.setTimeout(open, delay)
      }
    }

    open()
    return () => {
      stopped = true
      window.clearInterval(ping)
      window.clearTimeout(retry)
      socket?.close(1000)
    }
  }, [path, enabled])

  return { connected }
}

/**
 * The server's idea of "now", from the `serverNow` every state carries.
 *
 * A phone's clock can be minutes out. Deadlines and the countdown are the
 * server's, so they are drawn against the server's time: the offset is taken
 * from each state as it arrives, and a phone whose clock is wrong still
 * shows the right number of seconds.
 */
export function useServerClock() {
  const offsetRef = useRef(0)
  const sync = useCallback((serverNow: string | null | undefined) => {
    if (!serverNow) return
    const server = Date.parse(serverNow)
    if (!Number.isNaN(server)) offsetRef.current = server - Date.now()
  }, [])
  const now = useCallback(() => Date.now() + offsetRef.current, [])
  return { sync, now }
}

/** Re-renders every `ms` while `active`, for timers and countdowns. */
export function useTicker(active: boolean, ms = 250): number {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => setTick((t) => t + 1), ms)
    return () => window.clearInterval(id)
  }, [active, ms])
  return tick
}

/** Whether the reader asked for less motion. Count-ups skip straight to the end. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}
