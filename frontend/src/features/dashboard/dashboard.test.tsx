import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { makeMe, makeTicket, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const summary = {
  period_days: 30, total: 40, open: 24, new: 8, in_progress: 9, resolved: 7, closed: 9, overdue: 3, critical_open: 2,
  unassigned_open: 8, created_in_period: 40, resolved_in_period: 16, avg_resolution_hours: 37.5, avg_first_response_hours: 0.5,
  sla_compliance: null, technicians_available: null, active_work_orders: null,
  unavailable: { sla_compliance: 'SLA policies arrive in Phase 6.', technicians_available: 'Technician management arrives in Phase 5.', active_work_orders: 'Work orders arrive in Phase 5.' },
  generated_at: '2026-11-11T00:00:00Z',
}
const PRIORITIES = ['low', 'medium', 'high', 'critical']

beforeEach(() => {
  server.use(
    http.get(`${API}/dashboard/summary/`, () => HttpResponse.json(summary)),
    http.get(`${API}/dashboard/trends/`, ({ request }) => {
      const days = Number(new URL(request.url).searchParams.get('days'))
      return HttpResponse.json({ days: Array.from({ length: days }, (_, i) => ({ date: `2026-10-${String(i + 1).padStart(2, '0')}`, created: i % 3, resolved: i % 2 })) })
    }),
    http.get(`${API}/dashboard/breakdown/`, () => HttpResponse.json({
      status: [{ status: 'new', label: 'New', count: 8 }, { status: 'closed', label: 'Closed', count: 0 }],
      priority: PRIORITIES.map((p, i) => ({ priority: p, label: p, count: i + 1 })),
      category: [{ category: 'HVAC', count: 6 }],
    })),
    http.get(`${API}/dashboard/workload/`, () => HttpResponse.json({ agents: [{ user_id: 'u2', name: 'Ana Agent', open: 5, resolved: 4, avg_resolution_hours: 20 }] })),
    http.get(`${API}/dashboard/activity/`, () => HttpResponse.json({ events: [{ id: 1, event: 'status_changed', field: 'status', old_value: 'new', new_value: 'in_progress', actor: 'Ana Agent', ticket: { id: 't-1', reference: 'TCK-000001', title: 'AC' }, created_at: '2026-11-10T10:00:00Z' }] })),
    http.get(`${API}/tickets/`, () => HttpResponse.json(page([makeTicket()]))),
  )
})

describe('Dashboard', () => {
  it('shows KPI values from the API and links them to filtered ticket lists', async () => {
    renderRoute('/', { user: makeMe() })
    const overdue = (await screen.findByText('Overdue')).closest('a')!
    expect(overdue).toHaveTextContent('3')
    expect(overdue).toHaveAttribute('href', '/tickets?overdue=true')
    expect(screen.getByText('Avg resolution', { selector: 'span' }).parentElement).toHaveTextContent('37.5 h')
    expect(screen.getByText('Avg first response').parentElement).toHaveTextContent('30 min')
  })

  it('never shows a number for metrics whose module has not shipped', async () => {
    renderRoute('/', { user: makeMe() })
    const sla = (await screen.findByText('SLA compliance')).parentElement!
    expect(sla).toHaveTextContent('—')
    expect(sla).toHaveTextContent('SLA policies arrive in Phase 6.')
  })

  it('offers the trend as a table and follows the period selector', async () => {
    const user = userEvent.setup()
    renderRoute('/', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: 'View as table' }))
    const table = (await screen.findByRole('columnheader', { name: 'Created' })).closest('table')!
    expect(within(table).getAllByRole('row')).toHaveLength(31)
    await user.selectOptions(screen.getByLabelText('Period'), '7')
    expect(await screen.findByText('Per day, last 7 days')).toBeInTheDocument()
  })

  it('renders breakdowns, activity and workload', async () => {
    renderRoute('/', { user: makeMe() })
    expect(await screen.findByText('changed status from New to In progress')).toBeInTheDocument()
    expect(await screen.findByText('Ana Agent', { selector: 'td' })).toBeInTheDocument()
    expect(screen.getByText('HVAC')).toBeInTheDocument()
  })

  it('hides team workload from users who only see their own tickets', async () => {
    renderRoute('/', { user: makeMe('field_technician') })
    expect(await screen.findByText('An overview of your tickets.')).toBeInTheDocument()
    expect(screen.queryByText('Agent workload')).not.toBeInTheDocument()
  })
})
