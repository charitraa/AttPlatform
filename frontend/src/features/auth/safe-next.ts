/** Only allow same-app relative paths as post-login redirects (prevents open redirects). */
export function safeNextPath(next: string | null | undefined, fallback = '/'): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return fallback
  if (['/login', '/forgot-password', '/reset-password', '/accept-invite'].some((p) => next.startsWith(p))) return fallback
  return next
}
