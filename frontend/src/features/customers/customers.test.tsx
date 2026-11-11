import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { customerFixture, makeMe, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

describe('Customers', () => {
  it('lists customers and creates one, opening its page', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> = {}
    const created = customerFixture('cust-9', 'Everest Hotel', { open_ticket_count: 0, asset_count: 0 })
    server.use(
      http.get(`${API}/customers/`, () => HttpResponse.json(page([customerFixture('cust-1', 'Himalayan Bank', { tier: 'enterprise' })]))),
      http.post(`${API}/customers/`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(created, { status: 201 })
      }),
      http.get(`${API}/customers/cust-9/`, () => HttpResponse.json(created)),
      http.get(`${API}/customers/cust-9/contacts/`, () => HttpResponse.json([])),
      http.get(`${API}/assets/`, () => HttpResponse.json(page([]))),
      http.get(`${API}/tickets/`, () => HttpResponse.json(page([]))),
    )
    const { router } = renderRoute('/customers', { user: makeMe() })
    const row = (await screen.findByText('Himalayan Bank')).closest('tr')!
    expect(row).toHaveTextContent('enterprise')
    expect(row).toHaveTextContent('2')

    await user.click(screen.getByRole('button', { name: /add customer/i }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Add customer' }))
    expect(await within(dialog).findByText('Use at least 2 characters.')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Name'), 'Everest Hotel')
    await user.type(within(dialog).getByLabelText('Email'), 'not-an-email')
    await user.click(within(dialog).getByRole('button', { name: 'Add customer' }))
    expect(await within(dialog).findByText('Enter a valid email address.')).toBeInTheDocument()
    await user.clear(within(dialog).getByLabelText('Email'))
    await user.click(within(dialog).getByRole('button', { name: 'Add customer' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/customers/cust-9'))
    expect(body).toMatchObject({ name: 'Everest Hotel', tier: 'standard' })
    expect(await screen.findByRole('heading', { name: 'Everest Hotel' })).toBeInTheDocument()
  })

  it('shows the server duplicate-name error on the field', async () => {
    const user = userEvent.setup()
    server.use(
      http.get(`${API}/customers/`, () => HttpResponse.json(page([]))),
      http.post(`${API}/customers/`, () => HttpResponse.json(
        { error: { code: 'validation_error', message: 'Invalid input.', details: { name: ['A customer with this name already exists.'] }, request_id: 'r' } },
        { status: 400 },
      )),
    )
    renderRoute('/customers', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: /add customer/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Himalayan Bank')
    await user.click(within(dialog).getByRole('button', { name: 'Add customer' }))
    expect(await within(dialog).findByText('A customer with this name already exists.')).toBeInTheDocument()
  })

  it('is read-only for roles without customers.manage', async () => {
    server.use(http.get(`${API}/customers/`, () => HttpResponse.json(page([customerFixture('cust-1', 'Himalayan Bank')]))))
    renderRoute('/customers', { user: makeMe('field_technician', { permissions: ['customers.view'] }) })
    await screen.findByText('Himalayan Bank')
    expect(screen.queryByRole('button', { name: /add customer/i })).not.toBeInTheDocument()
  })
})
