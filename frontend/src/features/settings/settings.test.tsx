import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { makeMe } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const org = {
  id: 'org-1', name: 'Acme Facilities', slug: 'acme', timezone: 'UTC', locale: 'en', created_at: '2026-01-01T00:00:00Z',
  settings: { routing_policy: 'recommend', ai_enabled: true, ticket_auto_close_days: 7 },
}

describe('Organization settings', () => {
  beforeEach(() => server.use(http.get(`${API}/organization/`, () => HttpResponse.json(org))))

  it('saves profile and operational settings in one request', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> = {}
    server.use(
      http.patch(`${API}/organization/`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...org, name: 'Acme Ltd', settings: { ...org.settings, routing_policy: 'auto' } })
      }),
    )
    renderRoute('/settings/organization', { user: makeMe() })
    const name = await screen.findByLabelText('Organization name')
    expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled()
    await user.clear(name)
    await user.type(name, 'Acme Ltd')
    await user.selectOptions(screen.getByLabelText('Ticket routing'), 'auto')
    expect(screen.getByText(/AI assigns automatically when its confidence/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() =>
      expect(body).toEqual({
        name: 'Acme Ltd', timezone: 'UTC', locale: 'en',
        settings: { routing_policy: 'auto', ai_enabled: true, ticket_auto_close_days: 7 },
      }),
    )
  })

  it('validates the auto-close window', async () => {
    const user = userEvent.setup()
    renderRoute('/settings/organization', { user: makeMe() })
    const days = await screen.findByLabelText('Auto-close resolved tickets after (days)')
    await user.clear(days)
    await user.type(days, '120')
    await user.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText('Maximum 90 days.')).toBeInTheDocument()
  })

  it('is read-only without organization.manage', async () => {
    renderRoute('/settings/organization', { user: makeMe('support_agent') })
    expect(await screen.findByLabelText('Organization name')).toBeDisabled()
    expect(screen.getByText('Read only')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save settings' })).not.toBeInTheDocument()
  })
})

describe('Profile settings', () => {
  it('updates the profile and refreshes the signed-in user', async () => {
    const user = userEvent.setup()
    server.use(
      http.patch(`${API}/me/`, async ({ request }) => {
        const data = (await request.json()) as Record<string, string>
        return HttpResponse.json(makeMe('org_admin', { ...data, full_name: `${data.first_name} ${data.last_name}` }))
      }),
    )
    renderRoute('/settings/profile', { user: makeMe() })
    const first = await screen.findByLabelText('First name')
    expect(screen.getByLabelText('Email')).toBeDisabled()
    await user.clear(first)
    await user.type(first, 'Alicia')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(useAuthStore.getState().user?.first_name).toBe('Alicia'))
  })

  it('maps a wrong current password onto its field', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(`${API}/me/password/`, () =>
        HttpResponse.json(
          { error: { code: 'validation_error', message: 'Invalid input.', details: { current_password: ['Your current password is incorrect.'] }, request_id: 'r' } },
          { status: 400 },
        ),
      ),
    )
    renderRoute('/settings/profile', { user: makeMe() })
    await user.type(await screen.findByLabelText('Current password'), 'nope')
    await user.type(screen.getByLabelText('New password'), 'Another-Strong-99')
    await user.type(screen.getByLabelText('Confirm new password'), 'Another-Strong-99')
    await user.click(screen.getByRole('button', { name: 'Update password' }))
    expect(await screen.findByText('Your current password is incorrect.')).toBeInTheDocument()
    expect(screen.getByLabelText('Current password')).toHaveAttribute('aria-invalid', 'true')
  })
})
