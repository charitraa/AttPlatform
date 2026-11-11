import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { renderRoute } from '@/test/render'
import { API, fixtures, server } from '@/test/server'

describe('System status page', () => {
  it('shows live service health and latency from the API', async () => {
    renderRoute('/system')
    const services = await screen.findByRole('list')
    expect(await within(services).findByText('2.4 ms')).toBeInTheDocument()
    expect(within(services).getByText('PostgreSQL').closest('li')).toHaveTextContent('Operational')
    expect(within(services).getByText('Redis').closest('li')).toHaveTextContent('Operational')
    expect(await within(services).findByText('Real-time (WebSocket)')).toBeInTheDocument()
  })

  it('flags a failing dependency when readiness is degraded (503)', async () => {
    server.use(http.get(`${API}/health/ready/`, () => HttpResponse.json(fixtures.readyDegraded, { status: 503 })))
    renderRoute('/system')
    const redisRow = (await screen.findByText('2000.0 ms')).closest('li')!
    expect(redisRow).toHaveTextContent('Down')
  })

  it('labels the mock AI provider as demo mode', async () => {
    renderRoute('/system')
    expect(await screen.findByText('Demo mode')).toBeInTheDocument()
  })

  it('shows an error state with retry when the API is unreachable', async () => {
    server.use(http.get(`${API}/health/`, () => HttpResponse.error()))
    renderRoute('/system')
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to reach the server')
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})
