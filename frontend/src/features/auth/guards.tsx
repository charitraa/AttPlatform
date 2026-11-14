import { ShieldX } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { Navigate, Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { EmptyState } from '@/components/common/states'
import { Skeleton } from '@/components/ui/skeleton'
import { hasAnyPermission, useAuthStore } from '@/stores/auth'
import { safeNextPath } from './safe-next'

function FullPageLoader() {
  return (
    <div className="flex min-h-svh items-center justify-center" aria-busy="true" aria-label="Loading">
      <div className="grid w-64 gap-3"><Skeleton className="h-6" /><Skeleton className="h-6 w-2/3" /></div>
    </div>
  )
}

/** Ensures the session is restored; signed-out users go to /login?next=<current path>. */
export function RequireAuth() {
  const status = useAuthStore((s) => s.status)
  const bootstrap = useAuthStore((s) => s.bootstrap)
  const location = useLocation()

  useEffect(() => {
    if (status === 'idle') void bootstrap()
  }, [status, bootstrap])

  if (status === 'idle' || status === 'loading') return <FullPageLoader />
  if (status === 'anonymous') {
    if (location.pathname === '/' && !location.search) return <Navigate to="/welcome" replace />  // visitors see the landing page
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <Outlet />
}

/** Public auth pages: signed-in users are sent into the app (to ?next= when present). */
export function RedirectIfAuthenticated() {
  const [params] = useSearchParams()
  const status = useAuthStore((s) => s.status)
  const bootstrap = useAuthStore((s) => s.bootstrap)
  useEffect(() => {
    if (status === 'idle') void bootstrap()
  }, [status, bootstrap])
  if (status === 'idle' || status === 'loading') return <FullPageLoader />
  if (status === 'authenticated') return <Navigate to={safeNextPath(params.get('next'))} replace />
  return <Outlet />
}

/**
 * Hides a page from users lacking the permissions. This is a UX guard only:
 * the API enforces the same rules server-side.
 */
export function RequirePermission({ anyOf, children }: { anyOf?: string[]; children: ReactNode }) {
  const allowed = useAuthStore((s) => hasAnyPermission(s.user, anyOf ?? []))
  if (!allowed) {
    return (
      <EmptyState
        icon={ShieldX}
        className="mt-8"
        title="You don't have access to this page"
        description="Ask an organization administrator if you need access."
      />
    )
  }
  return <>{children}</>
}
