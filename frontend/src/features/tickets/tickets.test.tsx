import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { customerFixture, makeMe, makeTicket, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const error = (status: number, code: string, message: string, details: unknown = null) =>
  HttpResponse.json({ error: { code, message, details, request_id: 'r' } }, { status })

describe('Tickets list', () => {
  it('requests active tickets by default and reflects filters in the request and URL', async () => {
    const user = userEvent.setup()
    const requests: URLSearchParams[] = []
    server.use(
      http.get(`${API}/tickets/`, ({ request }) => {
        requests.push(new URL(request.url).searchParams)
        return HttpResponse.json(page([makeTicket(), makeTicket({ id: 't-2', reference: 'TCK-000002', title: 'Printer jam', priority: 'low' })]))
      }),
    )
    const { router } = renderRoute('/tickets', { user: makeMe() })
    expect(await screen.findByText('Printer jam')).toBeInTheDocument()
    expect(requests[0].get('status')).toBe('active')

    await user.selectOptions(screen.getByLabelText('Priority'), 'high,critical')
    await waitFor(() => expect(requests.at(-1)?.get('priority')).toBe('high,critical'))
    expect(router.state.location.search).toContain('priority=high%2Ccritical')

    await user.click(screen.getByRole('button', { name: /^priority/i }))
    await waitFor(() => expect(requests.at(-1)?.get('ordering')).toBe('-priority'))

    await user.type(screen.getByLabelText('Search tickets', { selector: 'input[placeholder^="Search text"]' }), 'TCK-2')
    await waitFor(() => expect(requests.at(-1)?.get('search')).toBe('TCK-2'))
  })

  it('shows an empty state with a create action', async () => {
    server.use(http.get(`${API}/tickets/`, () => HttpResponse.json(page([]))))
    renderRoute('/tickets', { user: makeMe() })
    expect(await screen.findByText('No tickets match these filters')).toBeInTheDocument()
  })
})

describe('Create ticket', () => {
  beforeEach(() => {
    server.use(
      http.get(`${API}/customers/`, () => HttpResponse.json(page([customerFixture('cust-1', 'Himalayan Bank')]))),
      http.get(`${API}/customers/cust-1/contacts/`, () =>
        HttpResponse.json([{ id: 'ct-1', name: 'Hari', email: '', phone: '', job_title: '', is_primary: true, has_portal_access: false, created_at: '' }])),
      http.get(`${API}/assets/`, () => HttpResponse.json(page([]))),
      http.get(`${API}/ticket-categories/`, () =>
        HttpResponse.json([{ id: 'cat-1', name: 'HVAC', full_name: 'HVAC', parent: null, department: '', description: '', default_priority: 'high', is_active: true }])),
    )
  })

  it('validates, loads contacts for the chosen customer, and submits', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> = {}
    server.use(
      http.post(`${API}/tickets/`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(makeTicket({ id: 'new-1', reference: 'TCK-000042' }), { status: 201 })
      }),
      http.get(`${API}/tickets/new-1/`, () => HttpResponse.json(makeTicket({ id: 'new-1', reference: 'TCK-000042' }))),
      http.get(`${API}/tickets/new-1/:sub/`, () => HttpResponse.json([])),
    )
    const { router } = renderRoute('/tickets/new', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: 'Create ticket' }))
    expect(await screen.findByText('Choose a customer.')).toBeInTheDocument()
    expect(screen.getByText(/at least 5 characters/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Title'), 'Server room too hot')
    await user.type(screen.getByLabelText('Description'), 'The AC is blowing warm air since 9am.')
    await screen.findByRole('option', { name: 'Himalayan Bank' })
    await user.selectOptions(screen.getByLabelText('Customer'), 'cust-1')
    await user.selectOptions(await screen.findByLabelText('Contact'), await screen.findByRole('option', { name: 'Hari (primary)' }))
    await user.selectOptions(screen.getByLabelText('Category'), 'cat-1')
    expect(screen.getByText('Default priority for this category: High')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Create ticket' }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/tickets/new-1'))
    expect(body).toMatchObject({
      title: 'Server room too hot', customer: 'cust-1', contact: 'ct-1', category: 'cat-1', asset: null, channel: 'phone',
    })
    expect(body).not.toHaveProperty('priority') // left to the category default
  })

  it('lets portal customers report an issue without choosing a customer or priority', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> = {}
    server.use(http.post(`${API}/tickets/`, async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>
      return HttpResponse.json(makeTicket(), { status: 201 })
    }))
    renderRoute('/tickets/new', { user: makeMe('customer') })
    await user.type(await screen.findByLabelText('Title'), 'Printer broken')
    await user.type(screen.getByLabelText('Description'), 'Paper jams on every print.')
    expect(screen.queryByLabelText('Customer')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Priority')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Create ticket' }))
    await waitFor(() => expect(body.title).toBe('Printer broken'))
    expect(body).not.toHaveProperty('customer')
    expect(body).not.toHaveProperty('priority')
  })
})

describe('Ticket detail', () => {
  const comments = [
    { id: 'c1', author: { id: 'u2', full_name: 'Ana Agent', email: '' }, body: 'Customer is VIP', visibility: 'internal', source: 'staff', attachments: [], created_at: '2026-11-10T10:00:00Z' },
    { id: 'c2', author: { id: 'u2', full_name: 'Ana Agent', email: '' }, body: 'We are on it', visibility: 'public', source: 'staff', attachments: [], created_at: '2026-11-10T10:05:00Z' },
  ]

  beforeEach(() => {
    server.use(
      http.get(`${API}/tickets/t-1/`, () => HttpResponse.json(makeTicket())),
      http.get(`${API}/tickets/t-1/comments/`, () => HttpResponse.json(comments)),
      http.get(`${API}/tickets/t-1/attachments/`, () => HttpResponse.json([])),
      http.get(`${API}/tickets/t-1/history/`, () => HttpResponse.json([
        { id: 1, event: 'created', field: '', old_value: null, new_value: null, actor: { id: 'u1', full_name: 'Alice Admin', email: '' }, actor_type: 'user', internal: false, created_at: '2026-11-10T09:00:00Z' },
        { id: 2, event: 'status_changed', field: 'status', old_value: 'new', new_value: 'open', actor: { id: 'u1', full_name: 'Alice Admin', email: '' }, actor_type: 'user', internal: false, created_at: '2026-11-10T09:30:00Z' },
      ])),
    )
  })

  it('shows details, the conversation with internal notes marked, and a readable timeline', async () => {
    renderRoute('/tickets/t-1', { user: makeMe() })
    expect(await screen.findByRole('heading', { name: 'AC not cooling' })).toBeInTheDocument()
    expect(screen.getByText('TCK-000001')).toBeInTheDocument()
    const note = (await screen.findByText('Customer is VIP')).closest('li')!
    expect(note).toHaveTextContent('Internal note')
    expect(await screen.findByText('changed status from New to Open')).toBeInTheDocument()
  })

  it('sends an internal note', async () => {
    const user = userEvent.setup()
    let body: unknown = null
    server.use(http.post(`${API}/tickets/t-1/comments/`, async ({ request }) => {
      body = await request.json()
      return HttpResponse.json({ ...comments[0], id: 'c3' }, { status: 201 })
    }))
    renderRoute('/tickets/t-1', { user: makeMe() })
    await user.click(await screen.findByRole('radio', { name: 'Internal note' }))
    await user.type(screen.getByLabelText('Internal note'), 'Check the compressor')
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await waitFor(() => expect(body).toEqual({ body: 'Check the compressor', visibility: 'internal' }))
  })

  it('requires resolution notes when resolving and shows the server error on the field', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> = {}
    server.use(http.post(`${API}/tickets/t-1/transition/`, async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>
      if (!body.resolution_notes) return error(400, 'validation_error', 'Invalid input.', { resolution_notes: ['Describe how the issue was resolved.'] })
      return HttpResponse.json(makeTicket({ status: 'resolved', resolution_notes: body.resolution_notes, allowed_transitions: ['closed', 'reopened'] }))
    }))
    renderRoute('/tickets/t-1', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: /change status/i }))
    await user.click(await screen.findByRole('menuitem', { name: 'Resolve' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    expect(await within(dialog).findByText('Describe how the issue was resolved.')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Resolution notes'), 'Replaced capacitor')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(body).toMatchObject({ status: 'resolved', resolution_notes: 'Replaced capacitor' })
  })

  it('hides staff tools from customers and offers to confirm a resolution', async () => {
    server.use(
      http.get(`${API}/tickets/t-1/`, () => HttpResponse.json(makeTicket({
        status: 'resolved', resolution_notes: 'Fixed', allowed_transitions: ['closed', 'reopened'],
        capabilities: { edit: false, assign: false, archive: false, internal_notes: false, comment: true },
      }))),
      http.get(`${API}/tickets/t-1/comments/`, () => HttpResponse.json([comments[1]])),
    )
    renderRoute('/tickets/t-1', { user: makeMe('customer') })
    await waitForTicketHeading()
    await userEvent.click(await screen.findByRole('button', { name: /change status/i }))
    expect(await screen.findByRole('menuitem', { name: 'Confirm resolution' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /assign/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: 'Internal note' })).not.toBeInTheDocument()
  })

  it('reports a missing or inaccessible ticket', async () => {
    server.use(http.get(`${API}/tickets/t-1/`, () => error(404, 'not_found', 'Not found.')))
    renderRoute('/tickets/t-1', { user: makeMe() })
    expect(await screen.findByText(/doesn't exist or you don't have access/)).toBeInTheDocument()
  })
})

async function waitForTicketHeading() {
  await screen.findByRole('heading', { name: 'AC not cooling' })
}
