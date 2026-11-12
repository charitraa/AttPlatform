import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeMe, makeTicket, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'
import { useAuthStore } from '@/stores/auth'

const note = (id: string, overrides: Record<string, unknown> = {}) => ({
  id, type: 'ticket_assigned', title: `TCK-00000${id} assigned to you`, body: 'ATM offline · Himalayan Bank', link: `/tickets/t-${id}`,
  data: {}, is_read: false, read_at: null, created_at: '2026-11-12T08:00:00Z', ...overrides,
})

/** A WebSocket the test controls: it records what the app sends and plays the server's side. */
class TestSocket {
  static all: TestSocket[] = []
  onopen: (() => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  sent: Record<string, unknown>[] = []
  readonly url: string
  constructor(url: string) {
    this.url = url
    TestSocket.all.push(this)
    queueMicrotask(() => this.onopen?.())
  }
  send(data: string) { this.sent.push(JSON.parse(data)) }
  close() {}
  serverSends(msg: object) { this.onmessage?.({ data: JSON.stringify(msg) }) }
  serverCloses(code: number) { this.onclose?.({ code }) }
}

beforeEach(() => { TestSocket.all = []; vi.stubGlobal('WebSocket', TestSocket) })
afterEach(() => vi.unstubAllGlobals())

async function authed(index = 0) {
  await waitFor(() => expect(TestSocket.all[index]?.sent[0]).toBeDefined())
  const ws = TestSocket.all[index]!
  act(() => ws.serverSends({ type: 'auth.ok', organization: 'acme' }))
  return ws
}

describe('event stream', () => {
  it('authenticates in the first message, never in the URL', async () => {
    renderRoute('/notifications', { user: makeMe() })
    const ws = await authed()
    expect(ws.url).toMatch(/^ws:\/\/[^/?]+\/ws\/events\/$/) // no token in the URL
    expect(ws.sent[0]).toEqual({ type: 'auth', token: useAuthStore.getState().accessToken, organization: 'acme' })
  })

  it('refetches tickets when the server says one changed', async () => {
    let fetches = 0
    server.use(http.get(`${API}/tickets/`, () => { fetches++; return HttpResponse.json(page([makeTicket()])) }))
    renderRoute('/tickets', { user: makeMe() })
    await screen.findByText('AC not cooling')
    const ws = await authed()
    const before = fetches
    act(() => ws.serverSends({ type: 'ticket.changed', ticket_id: 't-1', change: 'ticket.assigned' }))
    await waitFor(() => expect(fetches).toBeGreaterThan(before))
  })

  it('shows a toast for a new notification and updates the bell', async () => {
    let unread = 0
    server.use(http.get(`${API}/notifications/unread-count/`, () => HttpResponse.json({ unread })))
    renderRoute('/notifications', { user: makeMe() })
    const ws = await authed()
    unread = 1
    act(() => ws.serverSends({ type: 'notification.created', id: 'n1', kind: 'ticket_assigned', title: 'TCK-000041 assigned to you', link: '/tickets/t-41' }))
    expect(await screen.findByText('TCK-000041 assigned to you')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Notifications, 1 unread' })).toBeInTheDocument()
  })

  it('refreshes the token and reconnects when the server closes with 4401', async () => {
    let refreshed = 0
    server.use(http.post(`${API}/auth/refresh/`, () => { refreshed++; return HttpResponse.json({ access: 'fresh-token' }) }))
    renderRoute('/notifications', { user: makeMe() })
    const first = await authed()
    act(() => first.serverCloses(4401))
    await waitFor(() => expect(TestSocket.all[1]?.sent[0]).toMatchObject({ type: 'auth', token: 'fresh-token' }))
    expect(refreshed).toBe(1)
  })

  it('stays disconnected when the session is gone', async () => {
    renderRoute('/notifications', { user: makeMe() }) // default refresh handler answers 401
    const first = await authed()
    act(() => first.serverCloses(4401))
    await new Promise((r) => setTimeout(r, 100))
    expect(TestSocket.all).toHaveLength(1)
  })
})

describe('notifications', () => {
  it('lists notifications, opens one and marks it read, and marks all read', async () => {
    const user = userEvent.setup()
    const reads: string[] = []
    let readAll = false
    server.use(
      http.get(`${API}/notifications/unread-count/`, () => HttpResponse.json({ unread: readAll ? 0 : 2 })),
      http.get(`${API}/notifications/`, () => HttpResponse.json(page([note('1'), note('2', { is_read: true, read_at: '2026-11-12T09:00:00Z' })]))),
      http.post(`${API}/notifications/:id/read/`, ({ params }) => { reads.push(String(params.id)); return HttpResponse.json(note(String(params.id), { is_read: true })) }),
      http.post(`${API}/notifications/read-all/`, () => { readAll = true; return HttpResponse.json({ unread: 0 }) }),
    )
    renderRoute('/notifications', { user: makeMe() })
    const main = within(await screen.findByRole('main'))
    expect(await main.findByText('TCK-000001 assigned to you')).toBeInTheDocument()
    expect(main.getByText('(unread)')).toBeInTheDocument()
    await user.click(main.getByRole('button', { name: /mark all read/i }))
    await waitFor(() => expect(readAll).toBe(true))
    await user.click(main.getByRole('link', { name: /TCK-000001 assigned to you/ }))
    expect(reads).toEqual(['1'])
  })

  it('saves a preference change', async () => {
    const user = userEvent.setup()
    let saved: unknown = null
    const prefs = [
      { type: 'ticket_assigned', label: 'Ticket assigned to me', channel: 'in_app', enabled: true },
      { type: 'ticket_assigned', label: 'Ticket assigned to me', channel: 'email', enabled: true },
    ]
    server.use(
      http.get(`${API}/notifications/preferences/`, () => HttpResponse.json(prefs)),
      http.put(`${API}/notifications/preferences/`, async ({ request }) => { saved = await request.json(); return HttpResponse.json(prefs) }),
    )
    renderRoute('/notifications', { user: makeMe() })
    await user.click(await screen.findByRole('tab', { name: 'Preferences' }))
    await user.click(await screen.findByRole('checkbox', { name: 'Ticket assigned to me: email' }))
    await waitFor(() => expect(saved).toEqual([{ type: 'ticket_assigned', channel: 'email', enabled: false }]))
  })
})
