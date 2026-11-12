import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeMe, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const tech = (overrides: Record<string, unknown> = {}) => ({
  id: 'tech-1', user: { id: 'user-1', full_name: 'Alice Admin', email: 'alice@acme.test', phone: '' }, employee_id: 'T-1',
  status: 'available', home_lat: null, home_lng: null, max_daily_jobs: 6, hourly_cost: null, currency: 'USD',
  location_sharing_enabled: false, notes: '', service_areas: [], skills: [], active_jobs: 2, jobs_today: 1,
  created_at: '2026-11-01T00:00:00Z', ...overrides,
})

const listItem = (id: string, status: string, overrides: Record<string, unknown> = {}) => ({
  id, number: 1, reference: `WO-${id}`, title: `Job ${id}`, status, priority: 'medium',
  customer: { id: 'c-1', name: 'Hotel Annapurna' }, technician: { id: 'tech-1', user_id: 'user-1', name: 'Alice Admin' },
  ticket: null, service_address: 'Durbar Marg, Kathmandu', scheduled_start: null, scheduled_end: null,
  customer_confirmed_at: null, created_at: '2026-11-11T08:00:00Z', updated_at: '2026-11-11T08:00:00Z', ...overrides,
})

const detail = (id: string, status: string, next_steps: string[], overrides: Record<string, unknown> = {}) => ({
  ...listItem(id, status), description: 'Chiller tripping.', asset: null, lat: null, lng: null, actual_start: null,
  actual_end: null, service_notes: '', completion_summary: '', parts_used: [], labor_minutes: null, labor_cost: null,
  parts_cost: null, currency: 'USD', customer_signed_by: '', customer_rating: null, customer_comment: '',
  cancelled_reason: '', created_by: null, next_steps, appointment: null,
  capabilities: { edit: false, assign: false, schedule: false, decline: true, add_evidence: true, confirm: false },
  ...overrides,
})

function mockMyJobs({ me = tech(), active = [] as unknown[], completed = [] as unknown[] } = {}) {
  server.use(
    http.get(`${API}/technicians/me/`, () => HttpResponse.json(me)),
    http.get(`${API}/work-orders/`, ({ request }) => {
      const url = new URL(request.url)
      expect(url.searchParams.get('technician')).toBe('me')
      return HttpResponse.json(page(url.searchParams.get('status') === 'completed' ? completed : active))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('My jobs (technician view)', () => {
  it('puts the job in progress first and advances it from the page', async () => {
    const user = userEvent.setup()
    let body: unknown = null
    mockMyJobs({ active: [listItem('a', 'assigned'), listItem('b', 'en_route')] })
    let current = detail('b', 'en_route', ['on_site', 'cancelled'])
    server.use(
      http.get(`${API}/work-orders/b/`, () => HttpResponse.json(current)),
      http.post(`${API}/work-orders/b/advance/`, async ({ request }) => {
        body = await request.json()
        current = detail('b', 'on_site', ['in_progress'])
        return HttpResponse.json(current)
      }),
    )
    renderRoute('/my-jobs', { user: makeMe('field_technician') })

    expect(await screen.findByRole('button', { name: 'Arrived on site' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept job' })).not.toBeInTheDocument() // job a is only listed
    const upNext = screen.getByRole('region', { name: /up next/i })
    expect(within(upNext).getByText('Job a')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Arrived on site' }))
    await waitFor(() => expect(body).toEqual({ status: 'on_site' })) // sharing is off: no coordinates sent
    expect(await screen.findByRole('button', { name: 'Start work' })).toBeInTheDocument()
  })

  it('shows an empty state with no open jobs and lists recent completions awaiting sign-off', async () => {
    mockMyJobs({ completed: [listItem('z', 'completed')] })
    renderRoute('/my-jobs', { user: makeMe('field_technician') })
    expect(await screen.findByText('No open jobs')).toBeInTheDocument()
    expect(screen.getByText('awaiting sign-off')).toBeInTheDocument()
  })

  it('toggles duty status and location sharing through the profile endpoint', async () => {
    const user = userEvent.setup()
    const patches: unknown[] = []
    mockMyJobs()
    server.use(http.patch(`${API}/technicians/me/`, async ({ request }) => {
      const b = (await request.json()) as Record<string, unknown>
      patches.push(b)
      return HttpResponse.json(tech(b))
    }))
    renderRoute('/my-jobs', { user: makeMe('field_technician') })
    await user.click(await screen.findByRole('button', { name: 'Go off duty' }))
    await user.click(screen.getByLabelText('Share my location during jobs'))
    await waitFor(() => expect(patches).toEqual([{ status: 'off_duty' }, { location_sharing_enabled: true }]))
  })

  it('reports position only while sharing is on and the job is in the field', async () => {
    const posts: unknown[] = []
    const clearWatch = vi.fn()
    vi.stubGlobal('navigator', {
      ...navigator,
      geolocation: {
        watchPosition: (ok: PositionCallback) => {
          ok({ coords: { latitude: 27.7172, longitude: 85.324, accuracy: 12.4 } } as GeolocationPosition)
          return 7
        },
        clearWatch,
        getCurrentPosition: vi.fn(),
      },
    })
    mockMyJobs({ me: tech({ location_sharing_enabled: true }), active: [listItem('b', 'on_site')] })
    server.use(
      http.get(`${API}/work-orders/b/`, () => HttpResponse.json(detail('b', 'on_site', ['in_progress']))),
      http.post(`${API}/technicians/me/location/`, async ({ request }) => {
        posts.push(await request.json())
        return new HttpResponse(null, { status: 201 })
      }),
    )
    const { unmount } = renderRoute('/my-jobs', { user: makeMe('field_technician') })
    await waitFor(() => expect(posts).toEqual([{ lat: '27.717200', lng: '85.324000', accuracy_m: 12 }]))
    expect(await screen.findByText(/sharing your position with dispatch/i)).toBeInTheDocument()
    unmount()
    expect(clearWatch).toHaveBeenCalledWith(7)
  })

  it('does not start the location watcher for an accepted job that is not under way yet', async () => {
    const watchPosition = vi.fn()
    vi.stubGlobal('navigator', { ...navigator, geolocation: { watchPosition, clearWatch: vi.fn(), getCurrentPosition: vi.fn() } })
    mockMyJobs({ me: tech({ location_sharing_enabled: true }), active: [listItem('a', 'accepted')] })
    server.use(http.get(`${API}/work-orders/a/`, () => HttpResponse.json(detail('a', 'accepted', ['en_route']))))
    renderRoute('/my-jobs', { user: makeMe('field_technician') })
    expect(await screen.findByRole('button', { name: 'Start travelling' })).toBeInTheDocument()
    expect(watchPosition).not.toHaveBeenCalled()
  })
})

describe('Work order dispatch', () => {
  it('warns the dispatcher when reassigning releases the booked visit', async () => {
    const user = userEvent.setup()
    const manage = { edit: true, assign: true, schedule: true, decline: false, add_evidence: true, confirm: false }
    const wo = detail('w', 'assigned', ['cancelled'], { capabilities: manage })
    const candidate = (id: string, name: string) => ({
      technician_id: id, user_id: `u-${id}`, name, status: 'available', score: 0.8, factors: {}, active_jobs: 0,
      distance_km: null, matched_skills: [], missing_skills: [], blocked_reason: '',
    })
    server.use(
      http.get(`${API}/work-orders/w/`, () => HttpResponse.json(wo)),
      http.get(`${API}/work-orders/w/evidence/`, () => HttpResponse.json([])),
      http.get(`${API}/work-orders/w/status-log/`, () => HttpResponse.json([])),
      http.get(`${API}/work-orders/w/suggest-technicians/`, () =>
        HttpResponse.json({ weights: {}, candidates: [candidate('tech-2', 'Tina Gurung'), candidate('tech-1', 'Alice Admin')] })),
      http.post(`${API}/work-orders/w/assign/`, () => HttpResponse.json({
        ...wo, technician: { id: 'tech-2', user_id: 'u-tech-2', name: 'Tina Gurung' },
        warnings: ['The visit on 14 Nov 10:00 was released: Tina Gurung is already booked for WO-000001. Schedule a new time.'],
      })),
    )
    renderRoute('/work-orders/w', { user: makeMe('org_admin', { permissions: ['work_orders.view_all', 'work_orders.manage', 'customers.view', 'technicians.view'] }) })
    await user.click(await screen.findByRole('button', { name: /reassign/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('radio', { name: /tina gurung/i }))
    await user.click(within(dialog).getByRole('button', { name: 'Assign' }))
    expect(await screen.findByText(/was released: Tina Gurung is already booked/)).toBeInTheDocument()
  })
})
