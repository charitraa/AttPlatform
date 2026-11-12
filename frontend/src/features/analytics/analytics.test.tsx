import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeMe } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const report = (name: string, rows: Record<string, unknown>[]) => ({
  name, title: name === 'ticket_volume' ? 'Ticket volume' : 'SLA compliance', description: 'Report.', start: '2026-11-01', end: '2026-11-12',
  columns: name === 'ticket_volume'
    ? [{ key: 'date', label: 'Date', kind: 'date' }, { key: 'created', label: 'Created', kind: 'number' }, { key: 'resolved', label: 'Resolved', kind: 'number' }, { key: 'avg_resolution_h', label: 'Avg resolution (h)', kind: 'hours' }]
    : [{ key: 'priority', label: 'Priority', kind: 'text' }, { key: 'resolution_compliance', label: 'Resolution %', kind: 'percent' }],
  rows,
})

describe('analytics', () => {
  it('shows a report, switches report and date range', async () => {
    const user = userEvent.setup()
    const seen: string[] = []
    server.use(http.get(`${API}/analytics/reports/:name/`, ({ params, request }) => {
      const u = new URL(request.url)
      seen.push(`${params.name} ${u.searchParams.get('start')}→${u.searchParams.get('end')}`)
      return HttpResponse.json(params.name === 'ticket_volume'
        ? report('ticket_volume', [{ date: '2026-11-10', created: 3, resolved: 2, avg_resolution_h: 4 }, { date: '2026-11-11', created: 1, resolved: 0, avg_resolution_h: null }])
        : report('sla_compliance', [{ priority: 'High', resolution_compliance: 0.875 }]))
    }))
    renderRoute('/analytics?start=2026-11-01&end=2026-11-12', { user: makeMe() })
    const table = await screen.findByRole('table')
    expect(within(table).getByText('4.0')).toBeInTheDocument()
    expect(screen.getByText(/4/, { selector: 'span.font-medium' }).textContent).toBe('4') // created total
    await user.click(screen.getByRole('tab', { name: 'SLA compliance' }))
    expect(await screen.findByText('88%')).toBeInTheDocument()
    expect(seen).toEqual(['ticket_volume 2026-11-01→2026-11-12', 'sla_compliance 2026-11-01→2026-11-12'])
  })

  it('exports the current report as CSV with the selected dates', async () => {
    const user = userEvent.setup()
    let exported = ''
    server.use(
      http.get(`${API}/analytics/reports/:name/`, ({ request }) => {
        const u = new URL(request.url)
        if (u.searchParams.get('export') === 'csv') { exported = u.search; return new HttpResponse('Date,Created\n', { headers: { 'Content-Type': 'text/csv' } }) }
        return HttpResponse.json(report('ticket_volume', []))
      }),
    )
    const created: string[] = []
    URL.createObjectURL = (b: Blob) => { created.push(b.type); return 'blob:x' }
    URL.revokeObjectURL = () => {}
    renderRoute('/analytics?start=2026-11-01&end=2026-11-12', { user: makeMe() })
    expect(await screen.findByText('No data for this period')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /export csv/i }))
    await waitFor(() => expect(exported).toBe('?start=2026-11-01&end=2026-11-12&export=csv'))
  })
})
