import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const API = 'http://localhost:3000/api/v1'

export const fixtures = {
  health: { status: 'ok', version: '0.1.0', timestamp: '2026-11-11T12:00:00Z' },
  readyOk: { status: 'ok', checks: { database: { status: 'ok', latency_ms: 2.4 }, redis: { status: 'ok', latency_ms: 0.8 } } },
  readyDegraded: { status: 'degraded', checks: { database: { status: 'ok', latency_ms: 2.4 }, redis: { status: 'error', latency_ms: 2000 } } },
  meta: { name: 'ATT Platform', version: '0.1.0', environment: 'test', ai_provider: 'mock', ai_mock_mode: true, features: { ai: true } },
}

export const handlers = [
  // No session by default: tests that need one call signIn() from render.tsx.
  http.post(`${API}/auth/refresh/`, () =>
    HttpResponse.json({ error: { code: 'not_authenticated', message: 'No active session.', details: null, request_id: 'x' } }, { status: 401 }),
  ),
  http.post(`${API}/auth/logout/`, () => new HttpResponse(null, { status: 204 })),
  // Ticket pages mount the AI panel; default to "no analyses yet".
  http.get(`${API}/tickets/:id/ai/`, () => HttpResponse.json({ analyses: [], recommendations: [], ai_enabled: true })),
  http.get(`${API}/health/`, () => HttpResponse.json(fixtures.health)),
  http.get(`${API}/health/ready/`, () => HttpResponse.json(fixtures.readyOk)),
  http.get(`${API}/meta/`, () => HttpResponse.json(fixtures.meta)),
]

export const server = setupServer(...handlers)
