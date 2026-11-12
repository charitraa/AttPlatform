import type { Me } from '@/features/auth/api'

const ROLE_PERMISSIONS: Record<string, string[]> = {
  org_admin: [
    'organization.view', 'organization.manage', 'users.view', 'users.manage', 'invitations.manage', 'roles.view',
    'audit.view', 'tickets.view_all', 'tickets.create', 'tickets.update', 'tickets.assign', 'tickets.archive',
    'tickets.internal_notes', 'customers.view', 'customers.manage', 'assets.view', 'assets.manage', 'ai.use',
    'ai.override', 'knowledge.view', 'knowledge.manage', 'analytics.view',
  ],
  support_agent: [
    'organization.view', 'roles.view', 'users.view', 'tickets.view_all', 'tickets.create', 'tickets.update',
    'tickets.internal_notes', 'customers.view', 'customers.manage', 'assets.view', 'ai.use', 'knowledge.view',
  ],
  customer: ['organization.view', 'portal.access', 'tickets.view_own', 'tickets.create', 'feedback.submit'],
  field_technician: ['organization.view', 'tickets.view_own', 'work_orders.view_own', 'work_orders.execute'],
}

const ROLE_NAMES: Record<string, string> = {
  org_admin: 'Organization Admin', support_agent: 'Support Agent', field_technician: 'Field Technician',
  customer: 'Customer',
}

export function makeMe(role: keyof typeof ROLE_PERMISSIONS = 'org_admin', overrides: Partial<Me> = {}): Me {
  const organization = { id: 'org-1', name: 'Acme Facilities', slug: 'acme' }
  const roleRef = { code: role, name: ROLE_NAMES[role] }
  return {
    id: 'user-1', email: 'alice@acme.test', first_name: 'Alice', last_name: 'Admin', full_name: 'Alice Admin',
    phone: '', timezone: 'UTC', date_joined: '2026-01-01T00:00:00Z', last_login: '2026-11-10T09:00:00Z',
    organization, role: roleRef, permissions: ROLE_PERMISSIONS[role], memberships: [{ organization, role: roleRef }],
    ...overrides,
  }
}

export const roles = [
  { code: 'super_admin', name: 'Super Admin', description: '', rank: 100, is_system: true, permissions: [], assignable: false },
  { code: 'org_admin', name: 'Organization Admin', description: 'Manages the organization.', rank: 80, is_system: true, permissions: [], assignable: true },
  { code: 'support_agent', name: 'Support Agent', description: 'Handles tickets.', rank: 40, is_system: true, permissions: [], assignable: true },
  { code: 'customer', name: 'Customer', description: 'Portal user.', rank: 10, is_system: true, permissions: [], assignable: true },
]

export const member = (id: string, name: string, role = 'support_agent', is_active = true) => ({
  id,
  user: { id, email: `${name.toLowerCase().replace(' ', '.')}@acme.test`, first_name: name.split(' ')[0], last_name: name.split(' ')[1] ?? '', full_name: name, last_login: null },
  role: { code: role, name: roles.find((r) => r.code === role)?.name ?? role },
  is_active,
  joined_at: '2026-02-01T00:00:00Z',
})

export const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results })

const userRef = (id: string, full_name: string) => ({ id, full_name, email: `${id}@acme.test` })

export function makeTicket(overrides: Record<string, unknown> = {}) {
  return {
    id: 't-1', number: 1, reference: 'TCK-000001', title: 'AC not cooling', status: 'new', priority: 'high',
    priority_source: 'manual', channel: 'phone', tags: [], category: { id: 'cat-1', name: 'HVAC' },
    customer: { id: 'cust-1', name: 'Himalayan Bank' }, assigned_agent: null, assigned_technician: null,
    due_at: null, is_overdue: false, created_at: '2026-11-10T09:00:00Z', updated_at: '2026-11-10T09:00:00Z',
    archived_at: null, description: 'Server room is 31°C.', contact: { id: 'ct-1', name: 'Hari', email: 'hari@bank.test', phone: '' },
    asset: null, created_by: userRef('user-1', 'Alice Admin'), first_response_at: null, resolved_at: null,
    closed_at: null, resolution_notes: '', customer_confirmed_at: null,
    allowed_transitions: ['open', 'assigned', 'in_progress', 'pending_customer', 'escalated', 'resolved', 'closed'],
    capabilities: { edit: true, assign: true, archive: true, internal_notes: true, comment: true },
    ...overrides,
  }
}

export const customerFixture = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, name, type: 'business', tier: 'standard', email: '', phone: '', address_line1: '', address_line2: '', city: 'Kathmandu',
  region: '', postal_code: '', country: 'NP', notes: '', archived_at: null, created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z', open_ticket_count: 2, asset_count: 1, primary_contact: null, ...extra,
})
