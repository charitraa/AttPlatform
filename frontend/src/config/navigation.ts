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
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const navigation: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      { label: 'Dashboard', to: '/', icon: Gauge, phase: 3, summary: 'Ticket, SLA and technician KPIs computed by the backend.' },
      { label: 'Analytics', to: '/analytics', icon: BarChart3, phase: 7, summary: 'Performance, SLA compliance and AI accuracy reports with CSV export.' },
    ],
  },
  {
    label: 'Service desk',
    items: [
      { label: 'Tickets', to: '/tickets', icon: Ticket, phase: 3, summary: 'Ticket lifecycle, assignment, comments, attachments and audit trail.' },
      { label: 'Customers', to: '/customers', icon: Building2, phase: 3, summary: 'Customer accounts, contacts, ticket and service history.' },
      { label: 'Assets', to: '/assets', icon: Boxes, phase: 3, summary: 'Registered assets, warranties and maintenance history.' },
      { label: 'SLA', to: '/sla', icon: Timer, phase: 6, summary: 'SLA policies, business hours, breach detection and escalation.' },
    ],
  },
  {
    label: 'AI',
    items: [
      { label: 'AI Assistant', to: '/ai/assistant', icon: Sparkles, phase: 4, summary: 'Knowledge search and troubleshooting guidance with cited sources.' },
      { label: 'AI Insights', to: '/ai/insights', icon: BrainCircuit, phase: 4, summary: 'Recurring issues, patterns and SLA risk detected from ticket data.' },
    ],
  },
  {
    label: 'Field service',
    items: [
      { label: 'Work orders', to: '/work-orders', icon: ClipboardList, phase: 5, summary: 'Dispatch, on-site workflow, evidence and customer confirmation.' },
      { label: 'Technicians', to: '/technicians', icon: Wrench, phase: 5, summary: 'Skills, certifications, availability and service areas.' },
      { label: 'Schedule', to: '/schedule', icon: CalendarDays, phase: 5, summary: 'Technician calendar and customer appointments.' },
    ],
  },
  {
    label: 'Administration',
    items: [
      { label: 'Notifications', to: '/notifications', icon: Bell, phase: 6, summary: 'In-app, email and real-time notifications.' },
      { label: 'Integrations', to: '/integrations', icon: Plug, phase: 7, summary: 'Email, SMS, WhatsApp, webhooks and external systems.' },
      { label: 'Users', to: '/settings/users', icon: Users, phase: 2, summary: 'Users, roles and invitations.' },
      { label: 'Organization', to: '/settings/organization', icon: UserCog, phase: 2, summary: 'Organization profile and platform settings.' },
      { label: 'System status', to: '/system', icon: Activity, phase: 1, summary: 'Live health of the API, database, Redis and WebSocket.' },
    ],
  },
]

export const allNavItems = navigation.flatMap((g) => g.items)
