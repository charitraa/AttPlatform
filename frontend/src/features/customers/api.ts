import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

export const customerSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.enum(['business', 'individual']),
  tier: z.enum(['standard', 'premium', 'enterprise']),
  email: z.string(),
  phone: z.string(),
  address_line1: z.string(),
  address_line2: z.string(),
  city: z.string(),
  region: z.string(),
  postal_code: z.string(),
  country: z.string(),
  notes: z.string(),
  archived_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  open_ticket_count: z.number().optional(),
  asset_count: z.number().optional(),
  primary_contact: z.object({ id: z.string(), name: z.string(), email: z.string() }).nullable(),
})
export type Customer = z.infer<typeof customerSchema>

export const contactSchema = z.object({
  id: z.string(),
  name: z.string(),
  email: z.string(),
  phone: z.string(),
  job_title: z.string(),
  is_primary: z.boolean(),
  has_portal_access: z.boolean(),
  created_at: z.string(),
})
export type Contact = z.infer<typeof contactSchema>

export type CustomerInput = Partial<Omit<Customer, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'open_ticket_count' | 'asset_count' | 'primary_contact'>>

export interface CustomerFilters { search?: string; tier?: string; ordering?: string; page?: number; page_size?: number }

export function useCustomers(filters: CustomerFilters, enabled = true) {
  return useQuery({
    queryKey: ['customers', 'list', filters],
    queryFn: () => api.get(`/customers/${toQuery({ ...filters })}`, { schema: paginated(customerSchema) }),
    placeholderData: keepPreviousData,
    enabled,
  })
}

export function useCustomer(id: string | undefined) {
  return useQuery({
    queryKey: ['customers', 'detail', id],
    queryFn: () => api.get(`/customers/${id}/`, { schema: customerSchema }),
    enabled: !!id,
  })
}

export function useContacts(customerId: string | undefined) {
  return useQuery({
    queryKey: ['customers', 'detail', customerId, 'contacts'],
    queryFn: () => api.get(`/customers/${customerId}/contacts/`, { schema: z.array(contactSchema) }),
    enabled: !!customerId,
  })
}

export function useSaveCustomer(id?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: CustomerInput) =>
      id ? api.patch(`/customers/${id}/`, data, { schema: customerSchema }) : api.post('/customers/', data, { schema: customerSchema }),
    onSuccess: (c) => {
      qc.setQueryData(['customers', 'detail', c.id], c)
      void qc.invalidateQueries({ queryKey: ['customers', 'list'] })
    },
  })
}

export function useSaveContact(customerId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: Partial<Contact> & { name: string }) =>
      id
        ? api.patch(`/customers/${customerId}/contacts/${id}/`, data, { schema: contactSchema })
        : api.post(`/customers/${customerId}/contacts/`, data, { schema: contactSchema }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['customers'] }),
  })
}

export function useDeleteContact(customerId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/customers/${customerId}/contacts/${id}/`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['customers'] }),
  })
}
