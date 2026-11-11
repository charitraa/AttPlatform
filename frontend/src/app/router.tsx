import { createBrowserRouter, type RouteObject } from 'react-router-dom'
import { AppShell } from '@/components/layout/app-shell'
import { allNavItems } from '@/config/navigation'
import { SystemStatusPage } from '@/features/system/system-status-page'
import { ModulePage } from '@/pages/module-page'
import { NotFoundPage } from '@/pages/not-found-page'
import { RouteErrorPage } from '@/pages/route-error-page'

// Implemented feature routes. Everything else in the navigation renders an
// explicit "ships in Phase N" page until that phase replaces it.
const implemented: Record<string, RouteObject['element']> = {
  '/system': <SystemStatusPage />,
}

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RouteErrorPage />,
    children: [
      ...allNavItems.map((item) => ({
        ...(item.to === '/' ? { index: true } : { path: item.to.slice(1) }),
        element: implemented[item.to] ?? <ModulePage item={item} />,
      })),
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)
