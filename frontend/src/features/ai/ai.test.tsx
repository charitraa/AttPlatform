import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { makeMe, makeTicket, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'

const analysis = (overrides: Record<string, unknown> = {}) => ({
  id: 'an-1', ticket: 't-1', kind: 'classification', status: 'completed', provider: 'mock', model: 'mock-rules-v1',
  prompt_version: 'classification-v1', is_mock: true, input: {}, output: {}, confidence: 0.7, reasoning: '[mock] matched',
  error: '', latency_ms: 3, tokens_in: null, tokens_out: null, attempts: 1, trigger: 'ticket_created',
  created_at: '2026-11-11T10:00:00Z', completed_at: '2026-11-11T10:00:01Z', ...overrides,
})

const rec = (overrides: Record<string, unknown> = {}) => ({
  id: 'rec-1', type: 'priority', value: { priority: 'critical' }, previous_value: { priority: 'medium' }, confidence: 0.72,
  reasoning: '[mock] Keyword rules suggest critical.', status: 'pending', is_mock: true,
  ticket: { id: 't-1', reference: 'TCK-000001', title: 'AC not cooling' }, decided_by: null, decided_at: null,
  override_value: null, note: '', created_at: '2026-11-11T10:00:00Z', ...overrides,
})

function mockTicketPage(ai: Record<string, unknown>) {
  server.use(
    http.get(`${API}/tickets/t-1/`, () => HttpResponse.json(makeTicket())),
    http.get(`${API}/tickets/t-1/comments/`, () => HttpResponse.json([])),
    http.get(`${API}/tickets/t-1/attachments/`, () => HttpResponse.json([])),
    http.get(`${API}/tickets/t-1/history/`, () => HttpResponse.json([])),
    http.get(`${API}/tickets/t-1/ai/`, () => HttpResponse.json({ analyses: [], recommendations: [], ai_enabled: true, ...ai })),
  )
}

describe('AI panel on a ticket', () => {
  it('shows suggestions with confidence, reasoning and a demo label, and accepts one', async () => {
    const user = userEvent.setup()
    let decision: unknown = null
    mockTicketPage({ analyses: [analysis({ kind: 'priority' })], recommendations: [rec()] })
    server.use(http.post(`${API}/ai/recommendations/rec-1/decide/`, async ({ request }) => {
      decision = await request.json()
      return HttpResponse.json(rec({ status: 'accepted', decided_by: 'Alice Admin' }))
    }))
    renderRoute('/tickets/t-1', { user: makeMe() })
    const card = (await screen.findByText('Critical', { selector: 'span.font-medium' })).closest('li')!
    expect(card).toHaveTextContent('72% confident')
    expect(card).toHaveTextContent('(now Medium)')
    expect(card).toHaveTextContent('[mock] Keyword rules suggest critical.')
    expect(screen.getAllByText('Demo AI').length).toBeGreaterThan(0)
    await user.click(within(card).getByRole('button', { name: /accept/i }))
    await waitFor(() => expect(decision).toEqual({ decision: 'accept' }))
  })

  it('lets a manager override with a different value and a reason', async () => {
    const user = userEvent.setup()
    let decision: Record<string, unknown> = {}
    mockTicketPage({ analyses: [analysis({ kind: 'priority' })], recommendations: [rec()] })
    server.use(http.post(`${API}/ai/recommendations/rec-1/decide/`, async ({ request }) => {
      decision = (await request.json()) as Record<string, unknown>
      return HttpResponse.json(rec({ status: 'overridden' }))
    }))
    renderRoute('/tickets/t-1', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: 'Choose other' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'Apply' })).toBeDisabled()
    await user.selectOptions(within(dialog).getByLabelText('Priority'), 'high')
    await user.type(within(dialog).getByLabelText('Why? (optional)'), 'Only one room affected')
    await user.click(within(dialog).getByRole('button', { name: 'Apply' }))
    await waitFor(() => expect(decision).toEqual({ decision: 'override', value: { priority: 'high' }, note: 'Only one room affected' }))
  })

  it('shows suggestions read-only to agents without ai.override', async () => {
    mockTicketPage({ analyses: [analysis({ kind: 'priority' })], recommendations: [rec()] })
    renderRoute('/tickets/t-1', { user: makeMe('support_agent') })
    expect(await screen.findByText('72% confident')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /accept/i })).not.toBeInTheDocument()
  })

  it('explains a failed analysis without blocking the ticket', async () => {
    mockTicketPage({ analyses: [analysis({ status: 'failed', error: 'ProviderUnavailable: offline', output: null })] })
    renderRoute('/tickets/t-1', { user: makeMe() })
    expect(await screen.findByText(/ProviderUnavailable: offline/)).toBeInTheDocument()
    expect(screen.getByText(/works normally without it/)).toBeInTheDocument()
  })

  it('is hidden from users without ai.use', async () => {
    mockTicketPage({})
    renderRoute('/tickets/t-1', { user: makeMe('field_technician', { permissions: ['tickets.view_own'] }) })
    await screen.findByRole('heading', { name: 'AC not cooling' })
    expect(screen.queryByText('AI assistance')).not.toBeInTheDocument()
  })

  it('drafts a reply into the composer for review, never sending it', async () => {
    const user = userEvent.setup()
    let posted = false
    mockTicketPage({})
    server.use(
      http.post(`${API}/tickets/t-1/ai/`, () => HttpResponse.json([analysis({ id: 'an-9', kind: 'response_suggestion', status: 'pending', output: null })], { status: 202 })),
      http.get(`${API}/ai/analyses/an-9/`, () => HttpResponse.json(analysis({ id: 'an-9', kind: 'response_suggestion', output: { draft: 'Hi Hari, we are on it.', tone: 'calm', cited_article_ids: [] } }))),
      http.post(`${API}/tickets/t-1/comments/`, () => { posted = true; return HttpResponse.json({}, { status: 201 }) }),
    )
    renderRoute('/tickets/t-1', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: /suggest reply/i }))
    await waitFor(() => expect(screen.getByLabelText('Reply')).toHaveValue('Hi Hari, we are on it.'))
    expect(screen.getByText(/Draft suggested by AI/)).toBeInTheDocument()
    expect(posted).toBe(false)
  })
})

describe('AI Assistant page', () => {
  const answered = analysis({
    id: 'q-1', ticket: null, kind: 'knowledge_answer', confidence: 0.6, input: { question: 'How do I clear a jam?' },
    output: { answer: 'Open tray B.', steps: ['Open tray B', 'Remove paper'], confidence: 0.6, source_ids: ['article:a1', 'ticket:t9'],
      sources: [{ id: 'article:a1', kind: 'article', object_id: 'a1', title: 'Clearing jams' }, { id: 'ticket:t9', kind: 'ticket', object_id: 't9', title: 'TCK-000009 Jam' }] },
  })

  beforeEach(() => {
    server.use(http.get(`${API}/ai/assistant/`, () => HttpResponse.json([answered])))
  })

  it('shows answers with steps and linked sources, and submits new questions', async () => {
    const user = userEvent.setup()
    let asked: unknown = null
    server.use(http.post(`${API}/ai/assistant/`, async ({ request }) => {
      asked = await request.json()
      return HttpResponse.json(analysis({ id: 'q-2', kind: 'knowledge_answer', status: 'pending', output: null }), { status: 202 })
    }))
    renderRoute('/ai/assistant', { user: makeMe() })
    expect(await screen.findByText('Open tray B.')).toBeInTheDocument()
    expect(screen.getByText('Remove paper')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /TCK-000009 Jam/ })).toHaveAttribute('href', '/tickets/t9')
    expect(screen.getByText('60% confident')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Question'), 'Generator will not start')
    await user.click(screen.getByRole('button', { name: /ask/i }))
    await waitFor(() => expect(asked).toEqual({ question: 'Generator will not start' }))
  })

  it('lets editors review AI-extracted drafts and publish them', async () => {
    const user = userEvent.setup()
    let published = false
    const draft = {
      id: 'kb-1', title: 'How to resolve: AC not cooling', summary: 'Clean the coils', body: '## Problem', category: null,
      category_name: 'HVAC', tags: [], status: 'draft', source: 'ai_extracted',
      source_ticket: { id: 't-1', reference: 'TCK-000001', title: 'AC' }, author: null, reviewed_by: null, published_at: null,
      helpful_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
    }
    server.use(
      http.get(`${API}/knowledge/articles/`, ({ request }) =>
        HttpResponse.json(page(new URL(request.url).searchParams.get('status') === 'draft' ? [draft] : []))),
      http.post(`${API}/knowledge/articles/kb-1/publish/`, () => { published = true; return HttpResponse.json({ ...draft, status: 'published' }) }),
    )
    renderRoute('/ai/assistant', { user: makeMe() })
    await user.click(await screen.findByRole('tab', { name: 'Knowledge base' }))
    const item = (await screen.findByText('How to resolve: AC not cooling')).closest('li')!
    expect(item).toHaveTextContent('From a resolved ticket')
    expect(item).toHaveTextContent('TCK-000001')
    await user.click(within(item).getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(published).toBe(true))
  })
})

describe('AI Insights page', () => {
  const insight = {
    id: 'in-1', type: 'recurring_issue', title: 'Recurring HVAC issues', body: '[mock] 6 HVAC tickets.', evidence: ['6 tickets'],
    period_start: '2026-10-12T00:00:00Z', period_end: '2026-11-11T00:00:00Z', is_dismissed: false, is_mock: true,
    created_at: '2026-11-11T06:00:00Z',
  }

  beforeEach(() => {
    server.use(
      http.get(`${API}/ai/insights/`, () => HttpResponse.json(page([insight]))),
      http.get(`${API}/ai/status/`, () => HttpResponse.json({
        provider: 'mock', model: '', mock_mode: true, ai_enabled: true, auto_triage: false, routing_policy: 'recommend',
        auto_apply_min_confidence: 0.85,
        acceptance: [{ type: 'priority', prompt_version: 'priority-v1', is_mock: true, total: 10, accepted: 6, auto_applied: 0, overridden: 2, rejected: 2, pending: 0, acceptance_rate: 0.6 }],
      })),
    )
  })

  it('lists insights with evidence, explains demo mode and shows acceptance rates', async () => {
    renderRoute('/ai/insights', { user: makeMe() })
    expect(await screen.findByText('Recurring HVAC issues')).toBeInTheDocument()
    expect(screen.getByText('6 tickets')).toBeInTheDocument()
    expect(await screen.findByText(/running in demo mode/)).toBeInTheDocument()
    const row = (await screen.findByText('priority-v1')).closest('tr')!
    expect(row).toHaveTextContent('60%')
  })

  it('generates insights and waits for the run to finish', async () => {
    const user = userEvent.setup()
    let polled = 0
    server.use(
      http.post(`${API}/ai/insights/generate/`, () => HttpResponse.json(analysis({ id: 'run-1', kind: 'insights', status: 'pending', output: null }), { status: 202 })),
      http.get(`${API}/ai/analyses/run-1/`, () => { polled++; return HttpResponse.json(analysis({ id: 'run-1', kind: 'insights' })) }),
    )
    renderRoute('/ai/insights', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: /generate now/i }))
    expect(await screen.findByText('Insights updated')).toBeInTheDocument()
    expect(polled).toBeGreaterThan(0)
  })

  it('dismisses an insight', async () => {
    const user = userEvent.setup()
    let dismissed = false
    server.use(http.post(`${API}/ai/insights/in-1/dismiss/`, () => { dismissed = true; return HttpResponse.json({ ...insight, is_dismissed: true }) }))
    renderRoute('/ai/insights', { user: makeMe() })
    await user.click(await screen.findByRole('button', { name: 'Dismiss "Recurring HVAC issues"' }))
    await waitFor(() => expect(dismissed).toBe(true))
  })
})
