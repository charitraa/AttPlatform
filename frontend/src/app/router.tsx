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

const LandingPage = named(() => import('@/features/landing/landing-page'), 'LandingPage')
const LoginPage = named(() => import('@/features/auth/login-page'), 'LoginPage')
const ForgotPasswordPage = named(() => import('@/features/auth/forgot-password-page'), 'ForgotPasswordPage')
const ResetPasswordPage = named(() => import('@/features/auth/reset-password-page'), 'ResetPasswordPage')
const AcceptInvitePage = named(() => import('@/features/auth/accept-invite-page'), 'AcceptInvitePage')
const SystemStatusPage = named(() => import('@/features/system/system-status-page'), 'SystemStatusPage')
const UsersPage = named(() => import('@/features/users/users-page'), 'UsersPage')
const OrganizationSettingsPage = named(() => import('@/features/settings/organization-settings-page'), 'OrganizationSettingsPage')
const TicketsPage = named(() => import('@/features/tickets/tickets-page'), 'TicketsPage')
const CreateTicketPage = named(() => import('@/features/tickets/create-ticket-page'), 'CreateTicketPage')
const TicketDetailPage = named(() => import('@/features/tickets/ticket-detail-page'), 'TicketDetailPage')
const CustomersPage = named(() => import('@/features/customers/customers-page'), 'CustomersPage')
const CustomerDetailPage = named(() => import('@/features/customers/customer-detail-page'), 'CustomerDetailPage')
const AssetsPage = named(() => import('@/features/assets/assets-page'), 'AssetsPage')
const AssistantPage = named(() => import('@/features/ai/assistant-page'), 'AssistantPage')
const InsightsPage = named(() => import('@/features/ai/insights-page'), 'InsightsPage')
const WorkOrdersPage = named(() => import('@/features/field-service/work-orders-page'), 'WorkOrdersPage')
const WorkOrderDetailPage = named(() => import('@/features/field-service/work-order-detail-page'), 'WorkOrderDetailPage')
const TechniciansPage = named(() => import('@/features/field-service/technicians-page'), 'TechniciansPage')
const TechnicianDetailPage = named(() => import('@/features/field-service/technician-detail-page'), 'TechnicianDetailPage')
const SchedulePage = named(() => import('@/features/field-service/schedule-page'), 'SchedulePage')
const MyJobsPage = named(() => import('@/features/field-service/my-jobs-page'), 'MyJobsPage')
const NotificationsPage = named(() => import('@/features/notifications/notifications-page'), 'NotificationsPage')
const SLAPage = named(() => import('@/features/sla/sla-page'), 'SLAPage')
const HomeRoute = named(() => import('@/pages/home-route'), 'HomeRoute')
const PortalHomePage = named(() => import('@/features/portal/portal-home-page'), 'PortalHomePage')
const PortalNewTicketPage = named(() => import('@/features/portal/portal-new-ticket-page'), 'PortalNewTicketPage')
const PortalTicketPage = named(() => import('@/features/portal/portal-ticket-page'), 'PortalTicketPage')
const AnalyticsPage = named(() => import('@/features/analytics/analytics-page'), 'AnalyticsPage')
const IntegrationDetailPage = named(() => import('@/features/integrations/integration-detail-page'), 'IntegrationDetailPage')
const IntegrationsPage = named(() => import('@/features/integrations/integrations-page'), 'IntegrationsPage')
const ProfileSettingsPage = named(() => import('@/features/settings/profile-settings-page'), 'ProfileSettingsPage')

const page = (node: ReactNode) => <Suspense fallback={<PageFallback />}>{node}</Suspense>

// Implemented feature routes. Everything else in the navigation renders an
// explicit "ships in Phase N" page until that phase replaces it.
const implemented: Record<string, ReactNode> = {
  '/system': <SystemStatusPage />,
  '/': <HomeRoute />,
  '/portal': <PortalHomePage />,
  '/analytics': <AnalyticsPage />,
  '/integrations': <IntegrationsPage />,
  '/tickets': <TicketsPage />,
  '/customers': <CustomersPage />,
  '/assets': <AssetsPage />,
  '/ai/assistant': <AssistantPage />,
  '/ai/insights': <InsightsPage />,
  '/work-orders': <WorkOrdersPage />,
  '/technicians': <TechniciansPage />,
  '/schedule': <SchedulePage />,
  '/my-jobs': <MyJobsPage />,
  '/notifications': <NotificationsPage />,
  '/sla': <SLAPage />,
  '/settings/users': <UsersPage />,
  '/settings/organization': <OrganizationSettingsPage />,
}

/** Paths with a real page (the rest render the module placeholder). */
export const implementedPaths = Object.keys(implemented)

export const routes: RouteObject[] = [
  {
    errorElement: <RouteErrorPage />,
    children: [
      {
        element: <RedirectIfAuthenticated />,
        children: [
          { path: '/welcome', element: page(<LandingPage />) },
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
              {
                path: 'tickets/:id',
                element: <RequirePermission anyOf={['tickets.view_all', 'tickets.view_own']}>{page(<TicketDetailPage />)}</RequirePermission>,
              },
              {
                path: 'customers/:id',
                element: <RequirePermission anyOf={['customers.view']}>{page(<CustomerDetailPage />)}</RequirePermission>,
              },
              {
                path: 'work-orders/:id',
                element: <RequirePermission anyOf={['work_orders.view_all', 'work_orders.view_own']}>{page(<WorkOrderDetailPage />)}</RequirePermission>,
              },
              {
                path: 'technicians/:id',
                element: <RequirePermission anyOf={['technicians.view']}>{page(<TechnicianDetailPage />)}</RequirePermission>,
              },
              {
                path: 'integrations/:id',
                element: <RequirePermission anyOf={['integrations.manage']}>{page(<IntegrationDetailPage />)}</RequirePermission>,
              },
              {
                path: 'portal/new',
                element: <RequirePermission anyOf={['portal.access']}>{page(<PortalNewTicketPage />)}</RequirePermission>,
              },
              {
                path: 'portal/tickets/:id',
                element: <RequirePermission anyOf={['portal.access']}>{page(<PortalTicketPage />)}</RequirePermission>,
              },
              {
                path: 'tickets/new',
                element: <RequirePermission anyOf={['tickets.create']}>{page(<CreateTicketPage />)}</RequirePermission>,
              },
              { path: '*', element: <NotFoundPage /> },
            ],
          },
        ],
      },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)
