import type { Me } from '@/features/auth/api'

const ROLE_PERMISSIONS: Record<string, string[]> = {
  org_admin: [
    'organization.view', 'organization.manage', 'users.view', 'users.manage', 'invitations.manage', 'roles.view',
    'audit.view', 'tickets.view_all', 'customers.view', 'ai.use', 'analytics.view',
  ],
  support_agent: ['organization.view', 'roles.view', 'users.view', 'tickets.view_all', 'customers.view', 'ai.use'],
  field_technician: ['organization.view', 'tickets.view_own', 'work_orders.view_own', 'work_orders.execute'],
}

const ROLE_NAMES: Record<string, string> = {
  org_admin: 'Organization Admin', support_agent: 'Support Agent', field_technician: 'Field Technician',
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
