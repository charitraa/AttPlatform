import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'
import { API, server } from '@/test/server'
import { ApiError, apiRequest } from './client'

describe('apiRequest', () => {
  it('parses the backend error envelope into ApiError', async () => {
    server.use(
      http.post(`${API}/things/`, () =>
        HttpResponse.json(
          { error: { code: 'validation_error', message: 'Invalid input.', details: { title: ['Required'] }, request_id: 'abc12345' } },
          { status: 400, headers: { 'X-Request-ID': 'abc12345' } },
        ),
      ),
    )
    const err = (await apiRequest('/things/', { method: 'POST', body: {} }).catch((e: unknown) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 400, code: 'validation_error', message: 'Invalid input.', requestId: 'abc12345' })
    expect(err.details).toEqual({ title: ['Required'] })
  })

  it('reports network failures distinctly', async () => {
    server.use(http.get(`${API}/down/`, () => HttpResponse.error()))
    await expect(apiRequest('/down/')).rejects.toMatchObject({ status: 0, code: 'network_error' })
  })

  it('rejects responses that do not match the schema', async () => {
    server.use(http.get(`${API}/shape/`, () => HttpResponse.json({ unexpected: true })))
    await expect(apiRequest('/shape/', { schema: z.object({ id: z.string() }) })).rejects.toMatchObject({ code: 'invalid_response' })
  })

  it('accepts explicitly allowed non-2xx statuses', async () => {
    server.use(http.get(`${API}/ready/`, () => HttpResponse.json({ status: 'degraded' }, { status: 503 })))
    await expect(apiRequest('/ready/', { acceptStatus: [503] })).resolves.toEqual({ status: 'degraded' })
  })

  it('attaches the bearer token from the registered provider', async () => {
    let auth: string | null = null
    server.use(http.get(`${API}/me/`, ({ request }) => { auth = request.headers.get('Authorization'); return HttpResponse.json({}) }))
    const { useAuthStore } = await import('@/stores/auth')
    useAuthStore.setState({ accessToken: 'token-123' })
    await apiRequest('/me/')
    expect(auth).toBe('Bearer token-123')
  })
})

describe('automatic token refresh', () => {
  it('refreshes once on 401 and replays the request with the new token', async () => {
    const { useAuthStore } = await import('@/stores/auth')
    useAuthStore.setState({ status: 'authenticated', accessToken: 'expired', user: null })
    let refreshCalls = 0
    const seen: (string | null)[] = []
    server.use(
      http.post(`${API}/auth/refresh/`, () => { refreshCalls++; return HttpResponse.json({ access: 'renewed' }) }),
      http.get(`${API}/data/`, ({ request }) => {
        const auth = request.headers.get('Authorization')
        seen.push(auth)
        return auth === 'Bearer renewed'
          ? HttpResponse.json({ ok: true })
          : HttpResponse.json({ error: { code: 'token_not_valid', message: 'expired' } }, { status: 401 })
      }),
    )
    // Three concurrent requests share a single refresh (refresh tokens are single-use).
    const results = await Promise.all([apiRequest('/data/'), apiRequest('/data/'), apiRequest('/data/')])
    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }])
    expect(refreshCalls).toBe(1)
    expect(useAuthStore.getState().accessToken).toBe('renewed')
    expect(seen.filter((a) => a === 'Bearer expired')).toHaveLength(3)
  })

  it('signs the user out locally when the refresh token is no longer valid', async () => {
    const { useAuthStore } = await import('@/stores/auth')
    useAuthStore.setState({ status: 'authenticated', accessToken: 'expired', user: null })
    server.use(
      http.post(`${API}/auth/refresh/`, () => HttpResponse.json({ error: { code: 'session_expired', message: 'x' } }, { status: 401 })),
      http.get(`${API}/data/`, () => HttpResponse.json({ error: { code: 'token_not_valid', message: 'expired' } }, { status: 401 })),
    )
    await expect(apiRequest('/data/')).rejects.toMatchObject({ status: 401 })
    expect(useAuthStore.getState().status).toBe('anonymous')
  })
})
