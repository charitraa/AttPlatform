import type { LucideIcon } from 'lucide-react'
import {
  Activity, BarChart3, Boxes, Building2, CalendarDays, ClipboardList, Gauge, Plug, Sparkles,
  Ticket, Timer, Users, UserCog, Wrench, BrainCircuit, Bell,
} from 'lucide-react'

export interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  /** Roadmap phase that delivers this module (see docs/development-roadmap.md). */
  phase: number
  /** One-line description shown on the module page until it ships. */
  summary: string
  /** Visible / accessible when the user has ANY of these permissions (empty = every signed-in user). */
  permissions?: string[]
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const navigation: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      { label: 'Dashboard', to: '/', icon: Gauge, phase: 3, summary: 'Ticket, SLA and technician KPIs computed by the backend.', permissions: ['tickets.view_all', 'tickets.view_own'] },
      { label: 'Analytics', to: '/analytics', icon: BarChart3, phase: 7, summary: 'Performance, SLA compliance and AI accuracy reports with CSV export.', permissions: ['analytics.view'] },
    ],
  },
  {
    label: 'Service desk',
    items: [
      { label: 'Tickets', to: '/tickets', icon: Ticket, phase: 3, summary: 'Ticket lifecycle, assignment, comments, attachments and audit trail.', permissions: ['tickets.view_all', 'tickets.view_own'] },
      { label: 'Customers', to: '/customers', icon: Building2, phase: 3, summary: 'Customer accounts, contacts, ticket and service history.', permissions: ['customers.view'] },
      { label: 'Assets', to: '/assets', icon: Boxes, phase: 3, summary: 'Registered assets, warranties and maintenance history.', permissions: ['assets.view'] },
      { label: 'SLA', to: '/sla', icon: Timer, phase: 6, summary: 'SLA policies, business hours, breach detection and escalation.', permissions: ['sla.view'] },
    ],
  },
  {
    label: 'AI',
    items: [
      { label: 'AI Assistant', to: '/ai/assistant', icon: Sparkles, phase: 4, summary: 'Knowledge search and troubleshooting guidance with cited sources.', permissions: ['ai.use'] },
      { label: 'AI Insights', to: '/ai/insights', icon: BrainCircuit, phase: 4, summary: 'Recurring issues, patterns and SLA risk detected from ticket data.', permissions: ['ai.use'] },
    ],
  },
  {
    label: 'Field service',
    items: [
      { label: 'Work orders', to: '/work-orders', icon: ClipboardList, phase: 5, summary: 'Dispatch, on-site workflow, evidence and customer confirmation.', permissions: ['work_orders.view_all', 'work_orders.view_own'] },
      { label: 'Technicians', to: '/technicians', icon: Wrench, phase: 5, summary: 'Skills, certifications, availability and service areas.', permissions: ['technicians.view'] },
      { label: 'Schedule', to: '/schedule', icon: CalendarDays, phase: 5, summary: 'Technician calendar and customer appointments.', permissions: ['schedule.view'] },
    ],
  },
  {
    label: 'Administration',
    items: [
      { label: 'Notifications', to: '/notifications', icon: Bell, phase: 6, summary: 'In-app, email and real-time notifications.' },
      { label: 'Integrations', to: '/integrations', icon: Plug, phase: 7, summary: 'Email, SMS, WhatsApp, webhooks and external systems.', permissions: ['integrations.manage'] },
      { label: 'Users', to: '/settings/users', icon: Users, phase: 2, summary: 'Users, roles and invitations.', permissions: ['users.view'] },
      { label: 'Organization', to: '/settings/organization', icon: UserCog, phase: 2, summary: 'Organization profile and platform settings.', permissions: ['organization.view'] },
      { label: 'System status', to: '/system', icon: Activity, phase: 1, summary: 'Live health of the API, database, Redis and WebSocket.' },
    ],
  },
]

export const allNavItems = navigation.flatMap((g) => g.items)
