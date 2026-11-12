import type { z } from 'zod'
import { env } from '@/lib/env'

/** Mirrors the backend error envelope: {"error": {code, message, details, request_id}}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(status: number, code: string, message: string, details: unknown = null, requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

type TokenProvider = () => string | null
/** Obtains a new access token (via the refresh cookie); resolves null when the session is gone. */
type Refresher = () => Promise<string | null>

let getAccessToken: TokenProvider = () => null
let refreshAccessToken: Refresher | null = null
let refreshInFlight: Promise<string | null> | null = null

/** Registered by the auth store so the client stays decoupled from it. */
export function setAccessTokenProvider(provider: TokenProvider) {
  getAccessToken = provider
}

export function setTokenRefresher(refresher: Refresher | null) {
  refreshAccessToken = refresher
}

/** Concurrent 401s share one refresh request (refresh tokens rotate and are single-use). */
function refreshOnce(): Promise<string | null> {
  if (!refreshAccessToken) return Promise.resolve(null)
  refreshInFlight ??= refreshAccessToken().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

export interface RequestOptions<T> extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** Validate the response shape at runtime; mismatches surface as ApiError. */
  schema?: z.ZodType<T>
  /** Treat these non-2xx statuses as successful responses (e.g. 503 readiness). */
  acceptStatus?: number[]
  /** Internal: set on the retry after a token refresh to prevent loops. */
  _retried?: boolean
  /** Don't attempt a token refresh on 401 (used by the auth endpoints themselves). */
  skipAuthRefresh?: boolean
}

export async function apiRequest<T = unknown>(path: string, options: RequestOptions<T> = {}): Promise<T> {
  const { body, schema, acceptStatus = [], headers, _retried, skipAuthRefresh, ...init } = options
  const finalHeaders = new Headers(headers)
  finalHeaders.set('Accept', 'application/json')
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  if (body !== undefined && !isForm) finalHeaders.set('Content-Type', 'application/json')
  const token = getAccessToken()
  if (token) finalHeaders.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(`${env.apiBaseUrl}${path}`, {
      ...init,
      headers: finalHeaders,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network_error', 'Unable to reach the server. Check your connection.')
  }

  const requestId = response.headers.get('X-Request-ID')
  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      throw new ApiError(response.status, 'invalid_response', 'The server returned an unexpected response.', null, requestId)
    }
  }

  // Expired access token: refresh once, then replay the original request.
  if (response.status === 401 && token && !_retried && !skipAuthRefresh) {
    const fresh = await refreshOnce()
    if (fresh) return apiRequest<T>(path, { ...options, _retried: true })
  }

  if (!response.ok && !acceptStatus.includes(response.status)) {
    const err = (data as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error
    throw new ApiError(
      response.status,
      err?.code ?? 'http_error',
      err?.message ?? `Request failed with status ${response.status}.`,
      err?.details ?? null,
      requestId,
    )
  }

  if (schema) {
    const parsed = schema.safeParse(data)
    if (!parsed.success) {
      throw new ApiError(response.status, 'invalid_response', 'The server response did not match the expected format.', parsed.error.issues, requestId)
    }
    return parsed.data
  }
  return data as T
}

export const api = {
  get: <T>(path: string, options?: RequestOptions<T>) => apiRequest<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions<T>) => apiRequest<T>(path, { ...options, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions<T>) => apiRequest<T>(path, { ...options, method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions<T>) => apiRequest<T>(path, { ...options, method: 'PUT', body }),
  delete: <T>(path: string, options?: RequestOptions<T>) => apiRequest<T>(path, { ...options, method: 'DELETE' }),
}

/** Authenticated binary fetch (attachments). Retries once after a token refresh, like apiRequest. */
export async function apiBlob(url: string, retried = false): Promise<Blob> {
  const token = getAccessToken()
  // Server-provided paths look like /api/v1/...; resolve them against the configured API origin.
  const absolute = url.startsWith('/api/') ? env.apiBaseUrl.replace(/\/api\/v1\/?$/, '') + url : url
  const response = await fetch(absolute, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (response.status === 401 && token && !retried && (await refreshOnce())) return apiBlob(url, true)
  if (!response.ok) throw new ApiError(response.status, 'download_failed', 'The file could not be downloaded.')
  return response.blob()
}

/** Save a blob through a temporary object URL. */
export function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href, download: filename })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
