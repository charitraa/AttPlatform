import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'
import { API, server } from '@/test/server'
import { ApiError, apiRequest, setAccessTokenProvider } from './client'

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
    setAccessTokenProvider(() => 'token-123')
    await apiRequest('/me/')
    setAccessTokenProvider(() => null)
    expect(auth).toBe('Bearer token-123')
  })
})
