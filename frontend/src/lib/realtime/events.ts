import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { create } from 'zustand'
import { refreshOnce } from '@/lib/api/client'
import { wsUrl } from '@/lib/env'
import { useAuthStore } from '@/stores/auth'

export type StreamStatus = 'connecting' | 'open' | 'closed'

export const useRealtimeStore = create<{ status: StreamStatus; set: (s: StreamStatus) => void }>()((set) => ({
  status: 'closed',
  set: (status) => set({ status }),
}))

export type StreamMessage =
  | { type: 'ticket.changed'; ticket_id: string; change: string }
  | { type: 'work_order.changed'; work_order_id: string; change: string }
  | { type: 'sla.changed'; ticket_id: string; metric: string; change: string }
  | { type: 'notification.created'; id: string; kind: string; title: string; link: string }
  | { type: 'notification.read' }

const UNAUTHORIZED = 4401

/**
 * Server pushes carry IDs only; REST stays the source of truth. Each event invalidates the
 * cached queries it can affect, and TanStack Query refetches whatever is on screen.
 */
export function applyStreamMessage(qc: QueryClient, msg: StreamMessage, onNotification?: (m: Extract<StreamMessage, { type: 'notification.created' }>) => void) {
  switch (msg.type) {
    case 'ticket.changed':
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'tickets' && q.queryKey[1] !== 'categories' })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      break
    case 'sla.changed':
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'tickets' && q.queryKey[1] !== 'categories' })
      void qc.invalidateQueries({ queryKey: ['sla'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      break
    case 'work_order.changed':
      for (const key of ['work-orders', 'schedule', 'technicians', 'dashboard']) void qc.invalidateQueries({ queryKey: [key] })
      break
    case 'notification.created':
      void qc.invalidateQueries({ queryKey: ['notifications'] })
      onNotification?.(msg)
      break
    case 'notification.read':
      void qc.invalidateQueries({ queryKey: ['notifications'] })
      break
  }
}

/**
 * The authenticated event stream (`/ws/events/`). Mounted once in the app shell.
 * The access token is sent in the first message (never in the URL). When it expires the
 * server closes with 4401; we refresh through the shared single-flight refresher and reconnect.
 * Other drops reconnect with capped exponential backoff.
 */
export function useEventStream() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const authed = useAuthStore((s) => s.status === 'authenticated')
  const slug = useAuthStore((s) => s.user?.organization?.slug)
  const setStatus = useRealtimeStore((s) => s.set)

  useEffect(() => {
    if (!authed) return
    let socket: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0
    let disposed = false

    const schedule = (delay: number) => {
      if (!disposed) timer = setTimeout(connect, delay)
    }

    function connect() {
      setStatus('connecting')
      const ws = new WebSocket(wsUrl('/ws/events/'))
      socket = ws
      ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: useAuthStore.getState().accessToken, organization: slug }))
      ws.onmessage = (event) => {
        let msg: { type?: string }
        try { msg = JSON.parse(String(event.data)) } catch { return }
        if (msg.type === 'auth.ok') {
          attempt = 0
          setStatus('open')
          return
        }
        applyStreamMessage(qc, msg as StreamMessage, (n) =>
          toast(n.title, n.link ? { action: { label: 'View', onClick: () => navigate(n.link) } } : undefined))
      }
      ws.onclose = (event) => {
        if (socket === ws) socket = null
        setStatus('closed')
        if (disposed) return
        if (event.code === UNAUTHORIZED) {
          // Token expired or rejected: get a fresh one, then reconnect at once. No session → stay closed.
          void refreshOnce().then((token) => {
            if (token) schedule(attempt++ === 0 ? 0 : 5_000) // the refresher has stored the new token
          })
          return
        }
        schedule(Math.min(30_000, 1_000 * 2 ** attempt++))
      }
    }
    connect()

    return () => {
      disposed = true
      clearTimeout(timer)
      socket?.close()
      setStatus('closed')
    }
  }, [authed, slug, qc, navigate, setStatus])
}
