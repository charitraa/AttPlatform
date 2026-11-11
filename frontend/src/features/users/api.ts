import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

const roleRef = z.object({ code: z.string(), name: z.string() })

export const memberSchema = z.object({
  id: z.string(),
  user: z.object({
    id: z.string(), email: z.string(), first_name: z.string(), last_name: z.string(), full_name: z.string(),
    last_login: z.string().nullable(),
  }),
  role: roleRef,
  is_active: z.boolean(),
  joined_at: z.string(),
})
export type Member = z.infer<typeof memberSchema>

export const invitationSchema = z.object({
  id: z.string(),
  email: z.string(),
  role: roleRef,
  status: z.enum(['pending', 'accepted', 'revoked', 'expired']),
  expires_at: z.string(),
  accepted_at: z.string().nullable(),
  revoked_at: z.string().nullable(),
  invited_by: z.string().nullable(),
  created_at: z.string(),
})
export type Invitation = z.infer<typeof invitationSchema>

export const roleSchema = z.object({
  code: z.string(),
  name: z.string(),
  description: z.string(),
  rank: z.number(),
  is_system: z.boolean(),
  permissions: z.array(z.string()),
  assignable: z.boolean(),
})
export type Role = z.infer<typeof roleSchema>

export interface MemberFilters {
  search?: string
  role?: string
  is_active?: string
  page?: number
}

export const usersKeys = {
  members: (f: MemberFilters) => ['members', f] as const,
  invitations: (status: string) => ['invitations', status] as const,
  roles: ['roles'] as const,
}

export function useMembers(filters: MemberFilters) {
  return useQuery({
    queryKey: usersKeys.members(filters),
    queryFn: () => api.get(`/users/${toQuery({ ...filters })}`, { schema: paginated(memberSchema) }),
    placeholderData: keepPreviousData,
  })
}

export function useRoles() {
  return useQuery({
    queryKey: usersKeys.roles,
    queryFn: () => api.get('/roles/', { schema: z.array(roleSchema) }),
    staleTime: 5 * 60_000,
  })
}

export function useInvitations(status: string, enabled = true) {
  return useQuery({
    queryKey: usersKeys.invitations(status),
    queryFn: () => api.get(`/invitations/${toQuery({ status })}`, { schema: paginated(invitationSchema) }),
    enabled,
  })
}

export function useUpdateMember() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; role?: string; is_active?: boolean }) =>
      api.patch(`/users/${id}/`, data, { schema: memberSchema }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['members'] }),
  })
}

export function useInvite() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { email: string; role: string }) => api.post('/invitations/', data, { schema: invitationSchema }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['invitations'] }),
  })
}

export function useRevokeInvitation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/invitations/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['invitations'] }),
  })
}

export function useResendInvitation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post(`/invitations/${id}/resend/`, undefined, { schema: invitationSchema }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['invitations'] }),
  })
}
