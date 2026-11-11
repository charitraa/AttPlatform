import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'

export const organizationSchema = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  timezone: z.string(),
  locale: z.string(),
  settings: z.object({
    routing_policy: z.enum(['manual', 'recommend', 'auto']),
    ai_enabled: z.boolean(),
    ticket_auto_close_days: z.number(),
  }),
  created_at: z.string(),
})
export type Organization = z.infer<typeof organizationSchema>
export type OrganizationUpdate = Partial<Pick<Organization, 'name' | 'timezone' | 'locale'>> & {
  settings?: Partial<Organization['settings']>
}

export const organizationKey = ['organization'] as const

export function useOrganization() {
  return useQuery({ queryKey: organizationKey, queryFn: () => api.get('/organization/', { schema: organizationSchema }) })
}

export function useUpdateOrganization() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: OrganizationUpdate) => api.patch('/organization/', data, { schema: organizationSchema }),
    onSuccess: (org) => qc.setQueryData(organizationKey, org),
  })
}
