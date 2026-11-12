import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeMe, makeTicket, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const withSLA = (perms: string[] = []) => makeMe('org_admin', { permissions: [...makeMe().permissions, 'sla.view', ...perms] })

const clock = (overrides: Record<string, unknown> = {}) => ({
  id: 'sla-1', policy_name: 'Standard', business_hours_name: 'Standard hours', priority: 'high', started_at: '2026-11-12T08:00:00Z',
  warning_threshold_pct: 80, response_minutes: 60, response_due_at: '2026-11-12T09:00:00Z', response_status: 'met',
  responded_at: '2026-11-12T08:20:00Z', response_remaining_seconds: null, resolution_minutes: 480,
  resolution_due_at: '2026-11-12T16:00:00Z', resolution_status: 'warning', resolved_at: null, resolution_remaining_seconds: 5400,
  paused: false, paused_at: null, paused_seconds: 0, escalated_at: null,
  events: [{ id: 1, type: 'applied', metric: '', occurred_at: '2026-11-12T08:00:00Z', payload: {}, actor: null }], ...overrides,
})

function mockTicket(sla: ReturnType<typeof clock> | null) {
  server.use(
    http.get(`${API}/tickets/t-1/`, () => HttpResponse.json(makeTicket())),
    http.get(`${API}/tickets/t-1/comments/`, () => HttpResponse.json([])),
    http.get(`${API}/tickets/t-1/attachments/`, () => HttpResponse.json([])),
    http.get(`${API}/tickets/t-1/history/`, () => HttpResponse.json([])),
    http.get(`${API}/tickets/t-1/sla/`, () => HttpResponse.json(sla)),
  )
}

const panel = async () => within((await screen.findByText('SLA', { selector: '[data-slot="card-title"]' })).closest('[data-slot="card"]') as HTMLElement)

describe('SLA on the ticket page', () => {
  it('shows working time left, status per metric and the calendar', async () => {
    mockTicket(clock())
    renderRoute('/tickets/t-1', { user: withSLA() })
    const p = await panel()
    expect(p.getByText('Standard · Standard hours (working time)')).toBeInTheDocument()
    expect(p.getByText('At risk')).toBeInTheDocument()
    expect(p.getByText('1h 30m left')).toBeInTheDocument()
    expect(p.getByRole('progressbar', { name: 'Resolution: time used' })).toHaveAttribute('aria-valuenow', '81')
    expect(p.getByText('Met')).toBeInTheDocument() // first response
  })

  it('explains a paused clock and an overdue one', async () => {
    mockTicket(clock({ paused: true, paused_at: '2026-11-12T10:00:00Z', resolution_status: 'on_track', resolution_remaining_seconds: 7200,
      response_status: 'breached', responded_at: null, response_remaining_seconds: -1800 }))
    renderRoute('/tickets/t-1', { user: withSLA() })
    const p = await panel()
    expect(p.getByText(/clock paused/i)).toBeInTheDocument()
    expect(p.getByText('2h 00m left')).toBeInTheDocument()
    expect(p.getByText('Overdue by 30m')).toBeInTheDocument()
  })

  it('is hidden without sla.view', async () => {
    mockTicket(clock())
    renderRoute('/tickets/t-1', { user: makeMe('support_agent') })
    await screen.findByText('AC not cooling', { selector: 'h1' })
    expect(screen.queryByText('SLA', { selector: '[data-slot="card-title"]' })).not.toBeInTheDocument()
  })
})

describe('SLA in the ticket list', () => {
  it('shows the metric that needs attention first', async () => {
    const summary = { response_status: 'breached', response_due_at: '2026-11-12T09:00:00Z', resolution_status: 'on_track',
      resolution_due_at: '2026-11-12T16:00:00Z', paused: false }
    server.use(http.get(`${API}/tickets/`, () => HttpResponse.json(page([makeTicket({ sla: summary })]))))
    renderRoute('/tickets', { user: withSLA() })
    const row = (await screen.findByText('AC not cooling')).closest('tr')!
    expect(within(row).getByText('Breached')).toBeInTheDocument()
    expect(within(row).getByText(/Response due/)).toBeInTheDocument()
  })
})

describe('SLA management', () => {
  const hours = [{ id: 'h1', name: 'Standard hours', timezone: 'Asia/Kathmandu', schedule: { mon: [['09:00', '17:00']] }, holidays: [], policies: ['Standard'] }]
  const standard = {
    id: 'p1', name: 'Standard', description: '', is_default: true, is_active: true, business_hours: 'h1', business_hours_name: 'Standard hours',
    conditions: { categories: [], customer_tiers: [], channels: [] }, priority_order: 1000, escalate_on_breach: true,
    targets: ['low', 'medium', 'high', 'critical'].map((p) => ({ priority: p, first_response_minutes: 60, resolution_minutes: 480, warning_threshold_pct: 80 })),
  }

  it('creates a policy for enterprise customers and surfaces validation errors', async () => {
    const user = userEvent.setup()
    const posts: Record<string, unknown>[] = []
    server.use(
      http.get(`${API}/sla/policies/`, () => HttpResponse.json([standard])),
      http.get(`${API}/sla/business-hours/`, () => HttpResponse.json(hours)),
      http.get(`${API}/ticket-categories/`, () => HttpResponse.json([])),
      http.post(`${API}/sla/policies/`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        posts.push(body)
        if (posts.length === 1) {
          return HttpResponse.json({ error: { code: 'validation_error', message: "First response can't take longer than resolution.", details: {}, request_id: 'r' } }, { status: 400 })
        }
        return HttpResponse.json({ ...standard, ...body, id: 'p2', is_default: false }, { status: 201 })
      }),
    )
    renderRoute('/sla', { user: withSLA(['sla.manage']) })
    await user.click(await screen.findByRole('tab', { name: /policies/i }))
    await user.click(await screen.findByRole('button', { name: /new policy/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Enterprise')
    await user.click(within(dialog).getByLabelText('Enterprise'))
    for (const p of ['Low', 'Medium']) await user.click(within(dialog).getByRole('checkbox', { name: p }))
    await user.click(within(dialog).getByRole('button', { name: 'Save policy' }))
    expect(await within(dialog).findByText("First response can't take longer than resolution.")).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Save policy' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1]).toMatchObject({
      name: 'Enterprise', business_hours: 'h1', conditions: { customer_tiers: ['enterprise'], channels: [], categories: [] },
    })
    expect((posts[1].targets as { priority: string }[]).map((t) => t.priority)).toEqual(['high', 'critical'])
  })

  it('is read-only without sla.manage', async () => {
    const user = userEvent.setup()
    server.use(
      http.get(`${API}/sla/policies/`, () => HttpResponse.json([standard])),
      http.get(`${API}/sla/business-hours/`, () => HttpResponse.json(hours)),
    )
    renderRoute('/sla', { user: withSLA() })
    await user.click(await screen.findByRole('tab', { name: /policies/i }))
    expect(await screen.findByText('Default')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /new policy/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit Standard' })).not.toBeInTheDocument()
  })
})
