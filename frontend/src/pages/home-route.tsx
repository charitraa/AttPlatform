import { Navigate } from 'react-router-dom'
import { DashboardPage } from '@/features/dashboard/dashboard-page'
import { hasAnyPermission, useAuthStore } from '@/stores/auth'

/** Customers land on their requests; everyone else on the dashboard. */
export function HomeRoute() {
  const portalOnly = useAuthStore((s) => hasAnyPermission(s.user, ['portal.access']) && !hasAnyPermission(s.user, ['tickets.view_all']))
  return portalOnly ? <Navigate to="/portal" replace /> : <DashboardPage />
}
