import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

export const portalTicketSchema = z.object({
  id: z.string(), reference: z.string(), title: z.string(), description: z.string(), status: z.string(),
  status_label: z.string(), priority: z.string(), category: z.string().nullable(),
  asset: z.object({ id: z.string(), name: z.string() }).nullable(), handled_by: z.string().nullable(),
  resolution_notes: z.string(), created_at: z.string(), updated_at: z.string(), resolved_at: z.string().nullable(),
  closed_at: z.string().nullable(),
  actions: z.object({ reply: z.boolean(), confirm: z.boolean(), reopen: z.boolean(), rate: z.boolean() }),
  feedback: z.object({ rating: z.number(), comment: z.string(), created_at: z.string() }).nullable(),
})
export type PortalTicket = z.infer<typeof portalTicketSchema>
const commentSchema = z.object({ id: z.string(), author: z.string(), from_support: z.boolean(), body: z.string(), created_at: z.string() })
export type PortalComment = z.infer<typeof commentSchema>

const keys = { all: ['portal'] as const, list: (f: object) => ['portal', 'tickets', f] as const, one: (id: string) => ['portal', 'ticket', id] as const }

export function usePortalTickets(f: { state?: 'open' | 'done' | ''; search?: string; page?: number }) {
  return useQuery({
    queryKey: keys.list(f),
    queryFn: () => api.get(`/portal/tickets/${toQuery({ ...f })}`, { schema: paginated(portalTicketSchema) }),
    placeholderData: keepPreviousData,
  })
}
export const usePortalTicket = (id: string) => useQuery({ queryKey: keys.one(id), queryFn: () => api.get(`/portal/tickets/${id}/`, { schema: portalTicketSchema }) })
export const usePortalComments = (id: string) =>
  useQuery({ queryKey: [...keys.one(id), 'comments'], queryFn: () => api.get(`/portal/tickets/${id}/comments/`, { schema: z.array(commentSchema) }) })
export const usePortalOptions = () =>
  useQuery({
    queryKey: ['portal', 'options'],
    queryFn: () => api.get('/portal/options/', { schema: z.object({
      categories: z.array(z.object({ id: z.string(), name: z.string() })),
      assets: z.array(z.object({ id: z.string(), name: z.string(), asset_tag: z.string() })),
    }) }),
    staleTime: 5 * 60_000,
  })

export function usePortalMutations(id = '') {
  const qc = useQueryClient()
  const refresh = () => void qc.invalidateQueries({ queryKey: keys.all })
  return {
    create: useMutation({
      mutationFn: (body: { title: string; description: string; category?: string | null; asset?: string | null }) =>
        api.post('/portal/tickets/', body, { schema: portalTicketSchema }),
      onSuccess: refresh,
    }),
    reply: useMutation({
      mutationFn: (body: string) => api.post(`/portal/tickets/${id}/comments/`, { body }, { schema: z.array(commentSchema) }),
      onSuccess: (thread) => { qc.setQueryData([...keys.one(id), 'comments'], thread); refresh() },
    }),
    confirm: useMutation({ mutationFn: () => api.post(`/portal/tickets/${id}/confirm/`, {}, { schema: portalTicketSchema }), onSuccess: refresh }),
    reopen: useMutation({ mutationFn: (note: string) => api.post(`/portal/tickets/${id}/reopen/`, { note }, { schema: portalTicketSchema }), onSuccess: refresh }),
    rate: useMutation({
      mutationFn: (body: { rating: number; comment: string }) => api.post('/portal/feedback/', { ticket: id, ...body }),
      onSuccess: refresh,
    }),
  }
}
