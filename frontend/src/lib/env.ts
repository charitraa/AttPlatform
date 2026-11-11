/** Public, build-time configuration. Never put secrets in VITE_* variables. */
export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  /** Explicit WS origin; empty means "same origin as the page". */
  wsUrl: import.meta.env.VITE_WS_URL || '',
} as const

export function wsUrl(path: string): string {
  if (env.wsUrl) return `${env.wsUrl.replace(/\/$/, '')}${path}`
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}
