import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { makeMe, member, page, roles } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const alice = member('user-1', 'Alice Admin', 'org_admin')
const bob = member('user-2', 'Bob Agent', 'support_agent')
const carl = member('user-3', 'Carl Gone', 'support_agent', false)

beforeEach(() => {
  server.use(
    http.get(`${API}/roles/`, () => HttpResponse.json(roles)),
    http.get(`${API}/users/`, ({ request }) => {
      const url = new URL(request.url)
      const search = url.searchParams.get('search')?.toLowerCase() ?? ''
      const role = url.searchParams.get('role')
      return HttpResponse.json(
        page([alice, bob, carl].filter((m) => m.user.full_name.toLowerCase().includes(search) && (!role || m.role.code === role))),
      )
    }),
    http.get(`${API}/invitations/`, () => HttpResponse.json(page([]))),
  )
})

describe('Users page', () => {
  it('lists members with role and status, marking the current user', async () => {
    renderRoute('/settings/users', { user: makeMe() })
    const row = (await screen.findByText('Bob Agent')).closest('tr')!
    expect(row).toHaveTextContent('Support Agent')
    expect(row).toHaveTextContent('Active')
    expect((await screen.findByText('Carl Gone')).closest('tr')).toHaveTextContent('Deactivated')
    expect(screen.getByText('(you)')).toBeInTheDocument()
    // No actions on your own row
    expect(screen.queryByRole('button', { name: 'Actions for Alice Admin' })).not.toBeInTheDocument()
  })

  it('filters by search text (debounced) and role', async () => {
    const user = userEvent.setup()
    renderRoute('/settings/users', { user: makeMe() })
    await screen.findByText('Bob Agent')
    await user.type(screen.getByLabelText('Search users'), 'carl')
    await waitFor(() => expect(screen.queryByText('Bob Agent')).not.toBeInTheDocument())
    expect(screen.getByText('Carl Gone')).toBeInTheDocument()
    await user.clear(screen.getByLabelText('Search users'))
    await user.selectOptions(screen.getByLabelText('Filter by role'), 'org_admin')
    await waitFor(() => expect(screen.queryByText('Carl Gone')).not.toBeInTheDocument())
    expect(await screen.findByText(/Alice Admin/)).toBeInTheDocument() // after the cleared search debounces
  })

  it('is read-only for roles without users.manage / invitations.manage', async () => {
    renderRoute('/settings/users', { user: makeMe('support_agent') })
    await screen.findByText('Bob Agent')
    expect(screen.queryByRole('button', { name: /invite user/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /actions for/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Invitations' })).not.toBeInTheDocument()
  })

  it('invites a user, offering only roles the admin may grant', async () => {
    const user = userEvent.setup()
    let body: unknown = null
    server.use(
      http.post(`${API}/invitations/`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          id: 'inv-1', email: 'new@acme.test', role: { code: 'customer', name: 'Customer' }, status: 'pending',
          expires_at: '2026-11-18T00:00:00Z', accepted_at: null, revoked_at: null, invited_by: 'Alice Admin', created_at: '2026-11-11T00:00:00Z',
        }, { status: 201 })
      }),
    )
    renderRoute('/settings/users', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: /invite user/i }))
    const dialog = await screen.findByRole('dialog')
    const roleSelect = within(dialog).getByLabelText('Role')
    expect(within(roleSelect).queryByRole('option', { name: 'Super Admin' })).not.toBeInTheDocument()
    expect(roleSelect).toHaveValue('support_agent')

    await user.type(within(dialog).getByLabelText('Email'), 'new@acme.test')
    await user.selectOptions(roleSelect, 'customer')
    await user.click(within(dialog).getByRole('button', { name: 'Send invitation' }))
    await waitFor(() => expect(body).toEqual({ email: 'new@acme.test', role: 'customer' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('shows server conflicts inside the invite dialog', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(`${API}/invitations/`, () =>
        HttpResponse.json({ error: { code: 'conflict', message: 'This person is already a member of the organization.', details: null, request_id: 'r' } }, { status: 409 }),
      ),
    )
    renderRoute('/settings/users', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: /invite user/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Email'), 'bob.agent@acme.test')
    await user.click(within(dialog).getByRole('button', { name: 'Send invitation' }))
    expect(await within(dialog).findByText('This person is already a member of the organization.')).toBeInTheDocument()
  })

  it('changes a member role', async () => {
    const user = userEvent.setup()
    let body: unknown = null
    server.use(
      http.patch(`${API}/users/user-2/`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ ...bob, role: { code: 'org_admin', name: 'Organization Admin' } })
      }),
    )
    renderRoute('/settings/users', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: 'Actions for Bob Agent' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Change role' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'Save role' })).toBeDisabled() // unchanged
    await user.selectOptions(within(dialog).getByLabelText('Role'), 'org_admin')
    await user.click(within(dialog).getByRole('button', { name: 'Save role' }))
    await waitFor(() => expect(body).toEqual({ role: 'org_admin' }))
  })

  it('asks for confirmation before deactivating', async () => {
    const user = userEvent.setup()
    let body: unknown = null
    server.use(
      http.patch(`${API}/users/user-2/`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ ...bob, is_active: false })
      }),
    )
    renderRoute('/settings/users', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: 'Actions for Bob Agent' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Deactivate' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('signed out immediately')
    expect(body).toBeNull()
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(body).toEqual({ is_active: false }))
  })
})
