import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'
import { PRIORITIES, STATUSES } from './constants'

const userRef = z.object({ id: z.string(), full_name: z.string(), email: z.string() })
const namedRef = z.object({ id: z.string(), name: z.string() })

export const ticketListItemSchema = z.object({
  id: z.string(),
  number: z.number(),
  reference: z.string(),
  title: z.string(),
  status: z.enum(STATUSES),
  priority: z.enum(PRIORITIES),
  priority_source: z.enum(['manual', 'ai', 'policy']),
  channel: z.string(),
  tags: z.array(z.string()),
  category: namedRef.nullable(),
  customer: namedRef,
  assigned_agent: userRef.nullable(),
  assigned_technician: userRef.nullable(),
  due_at: z.string().nullable(),
  is_overdue: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
  archived_at: z.string().nullable(),
})
export type TicketListItem = z.infer<typeof ticketListItemSchema>

export const ticketSchema = ticketListItemSchema.extend({
  description: z.string(),
  contact: z.object({ id: z.string(), name: z.string(), email: z.string(), phone: z.string() }).nullable(),
  asset: z.object({ id: z.string(), asset_tag: z.string(), name: z.string(), under_warranty: z.boolean() }).nullable(),
  created_by: userRef.nullable(),
  first_response_at: z.string().nullable(),
  resolved_at: z.string().nullable(),
  closed_at: z.string().nullable(),
  resolution_notes: z.string(),
  customer_confirmed_at: z.string().nullable(),
  allowed_transitions: z.array(z.enum(STATUSES)),
  capabilities: z.object({
    edit: z.boolean(), assign: z.boolean(), archive: z.boolean(), internal_notes: z.boolean(), comment: z.boolean(),
  }),
})
export type Ticket = z.infer<typeof ticketSchema>

export const attachmentSchema = z.object({
  id: z.string(),
  original_name: z.string(),
  content_type: z.string(),
  size_bytes: z.number(),
  sha256: z.string(),
  visibility: z.enum(['public', 'internal']),
  uploaded_by: userRef.nullable(),
  comment: z.string().nullable(),
  created_at: z.string(),
  download_url: z.string(),
})
export type Attachment = z.infer<typeof attachmentSchema>

export const commentSchema = z.object({
  id: z.string(),
  author: userRef.nullable(),
  body: z.string(),
  visibility: z.enum(['public', 'internal']),
  source: z.string(),
  attachments: z.array(attachmentSchema),
  created_at: z.string(),
})
export type Comment = z.infer<typeof commentSchema>

export const historySchema = z.object({
  id: z.number(),
  event: z.string(),
  field: z.string(),
  old_value: z.unknown(),
  new_value: z.unknown(),
  actor: userRef.nullable(),
  actor_type: z.string(),
  internal: z.boolean(),
  created_at: z.string(),
})
export type HistoryEntry = z.infer<typeof historySchema>

export const categorySchema = z.object({
  id: z.string(),
  name: z.string(),
  full_name: z.string(),
  parent: z.string().nullable(),
  department: z.string(),
  description: z.string(),
  default_priority: z.enum(PRIORITIES),
  is_active: z.boolean(),
})
export type Category = z.infer<typeof categorySchema>

export interface TicketFilters {
  search?: string
  status?: string
  priority?: string
  assigned_agent?: string
  customer?: string
  category?: string
  overdue?: string
  archived?: string
  ordering?: string
  page?: number
}

export const ticketKeys = {
  list: (f: TicketFilters) => ['tickets', 'list', f] as const,
  detail: (id: string) => ['tickets', 'detail', id] as const,
  comments: (id: string) => ['tickets', 'detail', id, 'comments'] as const,
  attachments: (id: string) => ['tickets', 'detail', id, 'attachments'] as const,
  history: (id: string) => ['tickets', 'detail', id, 'history'] as const,
  categories: ['ticket-categories'] as const,
}

export function useTickets(filters: TicketFilters) {
  return useQuery({
    queryKey: ticketKeys.list(filters),
    queryFn: () => api.get(`/tickets/${toQuery({ ...filters })}`, { schema: paginated(ticketListItemSchema) }),
    placeholderData: keepPreviousData,
  })
}

export function useTicket(id: string) {
  return useQuery({ queryKey: ticketKeys.detail(id), queryFn: () => api.get(`/tickets/${id}/`, { schema: ticketSchema }) })
}

export function useComments(id: string) {
  return useQuery({ queryKey: ticketKeys.comments(id), queryFn: () => api.get(`/tickets/${id}/comments/`, { schema: z.array(commentSchema) }) })
}

export function useAttachments(id: string) {
  return useQuery({ queryKey: ticketKeys.attachments(id), queryFn: () => api.get(`/tickets/${id}/attachments/`, { schema: z.array(attachmentSchema) }) })
}

export function useHistory(id: string) {
  return useQuery({ queryKey: ticketKeys.history(id), queryFn: () => api.get(`/tickets/${id}/history/`, { schema: z.array(historySchema) }) })
}

export function useCategories() {
  return useQuery({
    queryKey: ticketKeys.categories,
    queryFn: () => api.get('/ticket-categories/', { schema: z.array(categorySchema) }),
    staleTime: 5 * 60_000,
  })
}

export interface CreateTicketInput {
  title: string
  description: string
  customer: string
  contact?: string | null
  asset?: string | null
  category?: string | null
  priority?: string
  channel?: string
  tags?: string[]
}

export function useCreateTicket() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: CreateTicketInput) => api.post('/tickets/', data, { schema: ticketSchema }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tickets', 'list'] }),
  })
}

/** Every ticket mutation returns the fresh ticket; write it to the cache and refresh dependants. */
function useTicketMutation<V>(id: string, fn: (vars: V) => Promise<Ticket>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (ticket) => {
      qc.setQueryData(ticketKeys.detail(id), ticket)
      void qc.invalidateQueries({ queryKey: ticketKeys.history(id) })
      void qc.invalidateQueries({ queryKey: ticketKeys.comments(id) })
      void qc.invalidateQueries({ queryKey: ['tickets', 'list'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

export function useUpdateTicket(id: string) {
  return useTicketMutation(id, (data: Partial<CreateTicketInput>) => api.patch(`/tickets/${id}/`, data, { schema: ticketSchema }))
}
export function useTransition(id: string) {
  return useTicketMutation(id, (data: { status: string; note?: string; resolution_notes?: string }) =>
    api.post(`/tickets/${id}/transition/`, data, { schema: ticketSchema }))
}
export function useAssign(id: string) {
  return useTicketMutation(id, (data: { agent?: string | null; technician?: string | null }) =>
    api.post(`/tickets/${id}/assign/`, data, { schema: ticketSchema }))
}
export function useEscalate(id: string) {
  return useTicketMutation(id, (reason: string) => api.post(`/tickets/${id}/escalate/`, { reason }, { schema: ticketSchema }))
}
export function useArchive(id: string) {
  return useTicketMutation(id, (archived: boolean) =>
    api.post(`/tickets/${id}/${archived ? 'archive' : 'unarchive'}/`, undefined, { schema: ticketSchema }))
}

export function useAddComment(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { body: string; visibility: 'public' | 'internal' }) =>
      api.post(`/tickets/${id}/comments/`, data, { schema: commentSchema }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ticketKeys.detail(id) })
    },
  })
}

export function useUploadAttachment(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, visibility }: { file: File; visibility: 'public' | 'internal' }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('visibility', visibility)
      return api.post(`/tickets/${id}/attachments/`, form, { schema: attachmentSchema })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ticketKeys.attachments(id) })
      void qc.invalidateQueries({ queryKey: ticketKeys.history(id) })
    },
  })
}
