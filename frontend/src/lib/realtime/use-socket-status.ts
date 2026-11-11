import { useEffect, useState } from 'react'
import { wsUrl } from '@/lib/env'

export type SocketStatus = 'connecting' | 'open' | 'closed'

/**
 * Connects to the system WebSocket and reports connection state, reconnecting
 * with capped exponential backoff. The authenticated event stream (`/ws/events/`)
 * arrives with notifications in Phase 6 and will reuse this pattern.
 */
export function useSocketStatus(path = '/ws/system/'): SocketStatus {
  const [status, setStatus] = useState<SocketStatus>('connecting')

  useEffect(() => {
    let socket: WebSocket | null = null
    let attempt = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    let disposed = false

    const connect = () => {
      setStatus('connecting')
      socket = new WebSocket(wsUrl(path))
      socket.onopen = () => {
        attempt = 0
        setStatus('open')
      }
      socket.onclose = () => {
        setStatus('closed')
        if (disposed) return
        const delay = Math.min(30_000, 1_000 * 2 ** attempt++)
        timer = setTimeout(connect, delay)
      }
    }
    connect()

    return () => {
      disposed = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [path])

  return status
}
