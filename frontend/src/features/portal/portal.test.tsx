import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeMe, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const customer = () => makeMe('customer')
const ticket = (overrides: Record<string, unknown> = {}) => ({
  id: 'p-1', reference: 'TCK-000041', title: 'Cold room not cooling', description: 'At 9°C since morning.', status: 'in_progress',
  status_label: 'In progress', priority: 'high', category: 'Refrigeration', asset: null, handled_by: 'Ana', resolution_notes: '',
  created_at: '2026-11-12T08:00:00Z', updated_at: '2026-11-12T09:00:00Z', resolved_at: null, closed_at: null,
  actions: { reply: true, confirm: false, reopen: false, rate: false }, feedback: null, ...overrides,
})

describe('customer portal', () => {
  it('lists requests by state', async () => {
    const user = userEvent.setup()
    const states: (string | null)[] = []
    server.use(http.get(`${API}/portal/tickets/`, ({ request }) => {
      const state = new URL(request.url).searchParams.get('state')
      states.push(state)
      return HttpResponse.json(page(state === 'done' ? [ticket({ id: 'p-2', title: 'Old one', status_label: 'Closed' })] : [ticket()]))
    }))
    renderRoute('/portal', { user: customer() })
    expect(await screen.findByText('Cold room not cooling')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Resolved' }))
    expect(await screen.findByText('Old one')).toBeInTheDocument()
    expect(states).toEqual(['open', 'done'])
  })

  it('raises a new request and validates it first', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> | null = null
    server.use(
      http.get(`${API}/portal/options/`, () => HttpResponse.json({ categories: [{ id: 'c1', name: 'Refrigeration' }], assets: [{ id: 'a1', name: 'Walk-in cold room', asset_tag: 'CR-1' }] })),
      http.post(`${API}/portal/tickets/`, async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return HttpResponse.json(ticket(), { status: 201 }) }),
      http.get(`${API}/portal/tickets/p-1/`, () => HttpResponse.json(ticket())),
      http.get(`${API}/portal/tickets/p-1/comments/`, () => HttpResponse.json([])),
    )
    renderRoute('/portal/new', { user: customer() })
    await user.click(await screen.findByRole('button', { name: 'Send request' }))
    expect(await screen.findByText('Give your request a short title.')).toBeInTheDocument()
    expect(body).toBeNull()
    await user.type(screen.getByLabelText("What's the problem?"), 'Cold room not cooling')
    await user.type(screen.getByLabelText('Details'), 'At 9°C since morning, compressor clicking.')
    await user.selectOptions(screen.getByLabelText('Equipment (optional)'), 'a1')
    await user.click(screen.getByRole('button', { name: 'Send request' }))
    await waitFor(() => expect(body).toEqual({ title: 'Cold room not cooling', description: 'At 9°C since morning, compressor clicking.', category: null, asset: 'a1' }))
    expect(await screen.findByRole('heading', { name: 'Cold room not cooling' })).toBeInTheDocument()
  })

  it('shows the conversation and sends a reply', async () => {
    const user = userEvent.setup()
    let sent: unknown = null
    const thread = [{ id: 'c1', author: 'Ana', from_support: true, body: 'Is the door sealing?', created_at: '2026-11-12T08:30:00Z' }]
    server.use(
      http.get(`${API}/portal/tickets/p-1/`, () => HttpResponse.json(ticket({ status_label: 'Waiting for your reply' }))),
      http.get(`${API}/portal/tickets/p-1/comments/`, () => HttpResponse.json(thread)),
      http.post(`${API}/portal/tickets/p-1/comments/`, async ({ request }) => {
        sent = await request.json()
        thread.push({ id: 'c2', author: 'Alice', from_support: false, body: 'Yes, it seals.', created_at: '2026-11-12T08:40:00Z' })
        return HttpResponse.json(thread)
      }),
    )
    renderRoute('/portal/tickets/p-1', { user: customer() })
    expect(await screen.findByText('Is the door sealing?')).toBeInTheDocument()
    expect(screen.getByText(/Ana · Support/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('We need a reply from you'), 'Yes, it seals.')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(sent).toEqual({ body: 'Yes, it seals.' }))
    expect(await screen.findByText('Yes, it seals.')).toBeInTheDocument()
  })

  it('reopens with a reason, confirms a fix and rates it', async () => {
    const user = userEvent.setup()
    const calls: [string, unknown][] = []
    let current = ticket({ status: 'resolved', status_label: 'Resolved', resolution_notes: 'Replaced the relay.', actions: { reply: true, confirm: true, reopen: true, rate: true } })
    server.use(
      http.get(`${API}/portal/tickets/p-1/`, () => HttpResponse.json(current)),
      http.get(`${API}/portal/tickets/p-1/comments/`, () => HttpResponse.json([])),
      http.post(`${API}/portal/tickets/p-1/reopen/`, async ({ request }) => { calls.push(['reopen', await request.json()]); return HttpResponse.json(current) }),
      http.post(`${API}/portal/tickets/p-1/confirm/`, () => { calls.push(['confirm', null]); current = { ...current, status: 'closed', status_label: 'Closed', actions: { ...current.actions, confirm: false, reopen: false } }; return HttpResponse.json(current) }),
      http.post(`${API}/portal/feedback/`, async ({ request }) => { calls.push(['rate', await request.json()]); return HttpResponse.json({}, { status: 201 }) }),
    )
    renderRoute('/portal/tickets/p-1', { user: customer() })
    expect(await screen.findByText('Replaced the relay.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /still broken/i }))
    expect(screen.getByRole('button', { name: 'Reopen request' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: /yes, it's fixed/i }))
    await waitFor(() => expect(calls).toEqual([['confirm', null]]))
    const rating = await screen.findByRole('radiogroup', { name: /rate how we handled/i })
    await user.click(within(rating).getByRole('radio', { name: /4 – Very good/ }))
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    await waitFor(() => expect(calls[1]).toEqual(['rate', { ticket: 'p-1', rating: 4, comment: '' }]))
  })
})
