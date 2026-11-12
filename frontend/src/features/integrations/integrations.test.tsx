import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeMe, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const admin = () => makeMe('org_admin', { permissions: [...makeMe().permissions, 'integrations.manage'] })
const field = (name: string, label: string, required = true) => ({ name, label, required, help: '', kind: 'string', choices: [] })
const catalog = {
  connectors: [
    { kind: 'webhook', provider: 'generic', label: 'Outbound webhooks', description: 'POST signed JSON events.', fields: [], secrets: [], generated_secrets: [], can_send: false, receives: false },
    { kind: 'inbound', provider: 'generic', label: 'Inbound webhook (tickets)', description: 'Create tickets.', fields: [], secrets: [], generated_secrets: ['signing_secret'], can_send: false, receives: true },
    { kind: 'sms', provider: 'twilio', label: 'SMS via Twilio', description: 'Send SMS.', fields: [field('from_number', 'From number')], secrets: [field('account_sid', 'Account SID'), field('auth_token', 'Auth token')], generated_secrets: [], can_send: true, receives: false },
  ],
  events: [{ type: 'ticket.created', label: 'A ticket was created' }, { type: 'sla.breached', label: 'An SLA target was breached' }],
}
const integration = (overrides: Record<string, unknown> = {}) => ({
  id: 'i1', kind: 'webhook', provider: 'generic', label: 'Outbound webhooks', name: 'ERP', config: {}, is_enabled: true, health: 'ok',
  last_success_at: '2026-11-12T08:00:00Z', last_error_at: null, last_error: '', credentials: {}, inbound_url: null, endpoint_count: 1,
  created_at: '2026-11-12T07:00:00Z', updated_at: '2026-11-12T07:00:00Z', ...overrides,
})

describe('integrations', () => {
  it('adds an SMS integration; credentials are sent but never displayed', async () => {
    const user = userEvent.setup()
    let body: Record<string, unknown> | null = null
    server.use(
      http.get(`${API}/integrations/catalog/`, () => HttpResponse.json(catalog)),
      http.get(`${API}/integrations/`, () => HttpResponse.json([])),
      http.post(`${API}/integrations/`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(integration({ id: 'i2', kind: 'sms', provider: 'twilio', label: 'SMS via Twilio', name: 'Twilio',
          config: { from_number: '+15005550006' }, credentials: { account_sid: { configured: true, hint: '…0000' }, auth_token: { configured: true, hint: '…9f3a' } } }), { status: 201 })
      }),
      http.get(`${API}/integrations/i2/`, () => HttpResponse.json(integration({ id: 'i2', kind: 'sms', provider: 'twilio', label: 'SMS via Twilio', name: 'Twilio',
        config: { from_number: '+15005550006' }, credentials: { account_sid: { configured: true, hint: '…0000' }, auth_token: { configured: true, hint: '…9f3a' } } }))),
    )
    renderRoute('/integrations', { user: admin() })
    await user.click((await screen.findAllByRole('button', { name: /add integration/i }))[0])
    await user.click(await screen.findByRole('button', { name: /SMS via Twilio/ }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText('From number'), '+15005550006')
    const token = within(dialog).getByLabelText('Auth token')
    expect(token).toHaveAttribute('type', 'password')
    await user.type(within(dialog).getByLabelText('Account SID'), 'AC0000')
    await user.type(token, 'tok-very-secret-9f3a')
    await user.click(within(dialog).getByRole('button', { name: 'Add integration' }))
    await waitFor(() => expect(body).toMatchObject({ kind: 'sms', provider: 'twilio', config: { from_number: '+15005550006' }, secrets: { account_sid: 'AC0000', auth_token: 'tok-very-secret-9f3a' } }))
    expect(await screen.findByText(/Saved \(…9f3a\)\. Leave empty to keep it\./)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('tok-very-secret')
  })

  it('shows a generated inbound signing secret once', async () => {
    const user = userEvent.setup()
    server.use(
      http.get(`${API}/integrations/catalog/`, () => HttpResponse.json(catalog)),
      http.get(`${API}/integrations/`, () => HttpResponse.json([])),
      http.post(`${API}/integrations/`, () => HttpResponse.json({ ...integration({ id: 'i3', kind: 'inbound', label: 'Inbound webhook (tickets)', name: 'Mail bridge', inbound_url: 'https://att.example/api/v1/webhooks/inbound/i3/' }), generated_secrets: { signing_secret: 'whsec_abc123' } }, { status: 201 })),
      http.get(`${API}/integrations/i3/`, () => HttpResponse.json(integration({ id: 'i3', kind: 'inbound', label: 'Inbound webhook (tickets)', name: 'Mail bridge', inbound_url: 'https://att.example/api/v1/webhooks/inbound/i3/', credentials: { signing_secret: { configured: true, hint: '…c123' } } }))),
    )
    renderRoute('/integrations', { user: admin() })
    await user.click((await screen.findAllByRole('button', { name: /add integration/i }))[0])
    await user.click(await screen.findByRole('button', { name: /Inbound webhook/ }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Add integration' }))
    const once = await screen.findByRole('dialog', { name: /signing secret/i })
    expect(within(once).getByLabelText('signing secret')).toHaveValue('whsec_abc123')
    await user.click(within(once).getByRole('button', { name: "I've saved it" }))
    expect(await screen.findByLabelText('inbound URL')).toHaveValue('https://att.example/api/v1/webhooks/inbound/i3/')
    expect(screen.queryByDisplayValue('whsec_abc123')).not.toBeInTheDocument()
  })

  it('tests the connection and retries a failed delivery', async () => {
    const user = userEvent.setup()
    let redelivered = ''
    server.use(
      http.get(`${API}/integrations/catalog/`, () => HttpResponse.json(catalog)),
      http.get(`${API}/integrations/i1/`, () => HttpResponse.json(integration())),
      http.post(`${API}/integrations/i1/test/`, () => HttpResponse.json({ ok: false, message: 'https://erp.example/hooks: HTTP 503' })),
      http.get(`${API}/integrations/i1/deliveries/`, () => HttpResponse.json(page([{
        id: 'd1', event_id: 'e1', event_type: 'sla.breached', url: 'https://erp.example/hooks', status: 'failed', attempts: 6, next_retry_at: null,
        response_code: 503, response_body: '', error: 'HTTP 503', delivered_at: null, payload: {}, created_at: '2026-11-12T08:00:00Z',
      }]))),
      http.post(`${API}/webhook-deliveries/:id/redeliver/`, ({ params }) => { redelivered = String(params.id); return HttpResponse.json({ id: 'd1', event_id: 'e1', event_type: 'sla.breached', url: 'x', status: 'pending', attempts: 0, next_retry_at: null, response_code: null, response_body: '', error: '', delivered_at: null, payload: {}, created_at: '2026-11-12T08:00:00Z' }, { status: 202 }) }),
    )
    renderRoute('/integrations/i1', { user: admin() })
    await user.click(await screen.findByRole('button', { name: /test connection/i }))
    expect(await screen.findByText('https://erp.example/hooks: HTTP 503')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Deliveries' }))
    await user.click(await screen.findByRole('button', { name: /retry now/i }))
    await waitFor(() => expect(redelivered).toBe('d1'))
  })
})
