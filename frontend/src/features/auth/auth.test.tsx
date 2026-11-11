import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { makeMe, page, roles } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'
import { safeNextPath } from './safe-next'

const error = (status: number, code: string, message: string, details: unknown = null) =>
  HttpResponse.json({ error: { code, message, details, request_id: 'req-1' } }, { status })

describe('login', () => {
  it('validates fields client-side without calling the API', async () => {
    let called = false
    server.use(http.post(`${API}/auth/login/`, () => { called = true; return HttpResponse.json({}) }))
    renderRoute('/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter a valid email address.')).toBeInTheDocument()
    expect(screen.getByText('Enter your password.')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(called).toBe(false)
  })

  it('shows a generic message for wrong credentials', async () => {
    server.use(http.post(`${API}/auth/login/`, () => error(401, 'invalid_credentials', 'Invalid email or password.')))
    renderRoute('/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'alice@acme.test')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
    expect(useAuthStore.getState().status).not.toBe('authenticated')
  })

  it('signs in, keeps the token in memory only, and returns to the requested page', async () => {
    let body: unknown = null
    server.use(
      http.post(`${API}/auth/login/`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ access: 'fresh-access', user: makeMe() })
      }),
      http.get(`${API}/organization/`, () =>
        HttpResponse.json({
          id: 'org-1', name: 'Acme Facilities', slug: 'acme', timezone: 'UTC', locale: 'en', created_at: '2026-01-01T00:00:00Z',
          settings: { routing_policy: 'recommend', ai_enabled: true, ticket_auto_close_days: 7 },
        }),
      ),
    )
    const { router } = renderRoute('/login?next=%2Fsettings%2Forganization')
    await userEvent.type(await screen.findByLabelText('Email'), 'alice@acme.test')
    await userEvent.type(screen.getByLabelText('Password'), 'Correct-Horse-42!')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Organization settings' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/settings/organization')
    expect(body).toEqual({ email: 'alice@acme.test', password: 'Correct-Horse-42!' })
    expect(useAuthStore.getState().accessToken).toBe('fresh-access')
    expect(JSON.stringify(localStorage)).not.toContain('fresh-access')
  })

  it('only accepts same-app redirect targets', () => {
    expect(safeNextPath('/tickets?x=1')).toBe('/tickets?x=1')
    expect(safeNextPath('//evil.example')).toBe('/')
    expect(safeNextPath('https://evil.example')).toBe('/')
    expect(safeNextPath('/\\evil.example')).toBe('/')
    expect(safeNextPath('/login')).toBe('/')
    expect(safeNextPath(null)).toBe('/')
  })
})

describe('route guards', () => {
  it('sends signed-out visitors to login, remembering where they were going', async () => {
    const { router } = renderRoute('/settings/users')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toBe('?next=%2Fsettings%2Fusers')
  })

  it('restores the session from the refresh cookie on load', async () => {
    server.use(
      http.post(`${API}/auth/refresh/`, () => HttpResponse.json({ access: 'restored' })),
      http.get(`${API}/me/`, () => HttpResponse.json(makeMe())),
      http.get(`${API}/roles/`, () => HttpResponse.json(roles)),
      http.get(`${API}/users/`, () => HttpResponse.json(page([]))),
      http.get(`${API}/invitations/`, () => HttpResponse.json(page([]))),
    )
    renderRoute('/settings/users')
    expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument()
    expect(useAuthStore.getState().accessToken).toBe('restored')
  })

  it('blocks pages the role cannot access and hides them from navigation', async () => {
    renderRoute('/settings/users', { user: makeMe('field_technician') })
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument()
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0]
    expect(nav).not.toHaveTextContent('Users')
    expect(nav).not.toHaveTextContent('Integrations')
    expect(nav).toHaveTextContent('Work orders')
  })

  it('signs out from the user menu and clears the session', async () => {
    const user = userEvent.setup()
    const { router } = renderRoute('/system', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: 'Account menu' }))
    await user.click(await screen.findByRole('menuitem', { name: /sign out/i }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
    expect(useAuthStore.getState()).toMatchObject({ status: 'anonymous', accessToken: null, user: null })
  })
})

describe('forgot password', () => {
  it('confirms without revealing whether the account exists', async () => {
    server.use(http.post(`${API}/auth/password/forgot/`, () => HttpResponse.json({ detail: 'ok' }, { status: 202 })))
    renderRoute('/forgot-password')
    await userEvent.type(await screen.findByLabelText('Email'), 'someone@acme.test')
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(await screen.findByText(/If an account exists for/)).toHaveTextContent('someone@acme.test')
  })
})

describe('reset password', () => {
  it('checks the confirmation matches and surfaces server password errors on the field', async () => {
    server.use(
      http.post(`${API}/auth/password/reset/`, () =>
        error(400, 'validation_error', 'Invalid input.', { new_password: ['This password is too common.'] }),
      ),
    )
    renderRoute('/reset-password?uid=abc&token=t-1')
    await userEvent.type(await screen.findByLabelText('New password'), 'password123456')
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'different-value')
    await userEvent.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByText('Passwords do not match.')).toBeInTheDocument()

    await userEvent.clear(screen.getByLabelText('Confirm new password'))
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'password123456')
    await userEvent.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByText('This password is too common.')).toBeInTheDocument()
  })

  it('explains an incomplete link', async () => {
    renderRoute('/reset-password')
    expect(await screen.findByRole('heading', { name: 'Invalid reset link' })).toBeInTheDocument()
  })
})

describe('accept invitation', () => {
  it('creates an account and signs in', async () => {
    let body: Record<string, unknown> = {}
    server.use(
      http.post(`${API}/auth/invitations/preview/`, () =>
        HttpResponse.json({ organization_name: 'Acme Facilities', email: 'new@acme.test', role_name: 'Support Agent', existing_account: false }),
      ),
      http.post(`${API}/auth/invitations/accept/`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ access: 'invited-access', user: makeMe('support_agent') }, { status: 201 })
      }),
    )
    renderRoute('/accept-invite?token=tok-123')
    expect(await screen.findByText('Acme Facilities')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('First name'), 'Nia')
    await userEvent.type(screen.getByLabelText('Last name'), 'New')
    await userEvent.type(screen.getByLabelText('Password'), 'Long-enough-pass-1')
    await userEvent.type(screen.getByLabelText('Confirm password'), 'Long-enough-pass-1')
    await userEvent.click(screen.getByRole('button', { name: 'Accept invitation' }))
    await waitFor(() => expect(useAuthStore.getState().accessToken).toBe('invited-access'))
    expect(body).toMatchObject({ token: 'tok-123', first_name: 'Nia', last_name: 'New', password: 'Long-enough-pass-1' })
  })

  it('asks existing users only for their current password', async () => {
    server.use(
      http.post(`${API}/auth/invitations/preview/`, () =>
        HttpResponse.json({ organization_name: 'Acme Facilities', email: 'known@x.test', role_name: 'Support Agent', existing_account: true }),
      ),
    )
    renderRoute('/accept-invite?token=tok-9')
    expect(await screen.findByLabelText('Your current password')).toBeInTheDocument()
    expect(screen.queryByLabelText('First name')).not.toBeInTheDocument()
  })

  it('shows a clear message for invalid or expired links', async () => {
    server.use(http.post(`${API}/auth/invitations/preview/`, () => error(400, 'invalid_invitation', 'Invalid.')))
    renderRoute('/accept-invite?token=bad')
    expect(await screen.findByRole('heading', { name: 'Invitation unavailable' })).toBeInTheDocument()
  })
})
