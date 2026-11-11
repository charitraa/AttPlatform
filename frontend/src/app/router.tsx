import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, type RouteObject } from 'react-router-dom'
import { AppShell } from '@/components/layout/app-shell'
import { PageFallback } from '@/components/common/page-fallback'
import { allNavItems } from '@/config/navigation'
import { RedirectIfAuthenticated, RequireAuth, RequirePermission } from '@/features/auth/guards'
import { ModulePage } from '@/pages/module-page'
import { NotFoundPage } from '@/pages/not-found-page'
import { RouteErrorPage } from '@/pages/route-error-page'

// Route-level code splitting: each page is its own chunk.
const named = <T extends Record<string, unknown>>(loader: () => Promise<T>, name: keyof T) =>
  lazy(async () => ({ default: (await loader())[name] as React.ComponentType }))

const LoginPage = named(() => import('@/features/auth/login-page'), 'LoginPage')
const ForgotPasswordPage = named(() => import('@/features/auth/forgot-password-page'), 'ForgotPasswordPage')
const ResetPasswordPage = named(() => import('@/features/auth/reset-password-page'), 'ResetPasswordPage')
const AcceptInvitePage = named(() => import('@/features/auth/accept-invite-page'), 'AcceptInvitePage')
const SystemStatusPage = named(() => import('@/features/system/system-status-page'), 'SystemStatusPage')
const UsersPage = named(() => import('@/features/users/users-page'), 'UsersPage')
const OrganizationSettingsPage = named(() => import('@/features/settings/organization-settings-page'), 'OrganizationSettingsPage')
const ProfileSettingsPage = named(() => import('@/features/settings/profile-settings-page'), 'ProfileSettingsPage')

const page = (node: ReactNode) => <Suspense fallback={<PageFallback />}>{node}</Suspense>

// Implemented feature routes. Everything else in the navigation renders an
// explicit "ships in Phase N" page until that phase replaces it.
const implemented: Record<string, ReactNode> = {
  '/system': <SystemStatusPage />,
  '/settings/users': <UsersPage />,
  '/settings/organization': <OrganizationSettingsPage />,
}

export const routes: RouteObject[] = [
  {
    errorElement: <RouteErrorPage />,
    children: [
      {
        element: <RedirectIfAuthenticated />,
        children: [
          { path: '/login', element: page(<LoginPage />) },
          { path: '/forgot-password', element: page(<ForgotPasswordPage />) },
        ],
      },
      // Reachable whether or not someone is signed in (links arrive by email).
      { path: '/reset-password', element: page(<ResetPasswordPage />) },
      { path: '/accept-invite', element: page(<AcceptInvitePage />) },
      {
        element: <RequireAuth />,
        children: [
          {
            path: '/',
            element: <AppShell />,
            children: [
              ...allNavItems.map((item) => ({
                ...(item.to === '/' ? { index: true } : { path: item.to.slice(1) }),
                element: (
                  <RequirePermission anyOf={item.permissions}>
                    {page(implemented[item.to] ?? <ModulePage item={item} />)}
                  </RequirePermission>
                ),
              })),
              { path: 'settings/profile', element: page(<ProfileSettingsPage />) },
              { path: '*', element: <NotFoundPage /> },
            ],
          },
        ],
      },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)
