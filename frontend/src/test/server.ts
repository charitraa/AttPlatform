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
  http.get(`${API}/health/`, () => HttpResponse.json(fixtures.health)),
  http.get(`${API}/health/ready/`, () => HttpResponse.json(fixtures.readyOk)),
  http.get(`${API}/meta/`, () => HttpResponse.json(fixtures.meta)),
]

export const server = setupServer(...handlers)
