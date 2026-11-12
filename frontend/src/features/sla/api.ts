import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { toQuery } from '@/lib/api/pagination'
import { PRIORITIES } from '@/features/tickets/constants'

export const METRIC_STATUSES = ['on_track', 'warning', 'breached', 'met'] as const
export type MetricStatus = (typeof METRIC_STATUSES)[number]
export const METRIC_LABEL: Record<MetricStatus, string> = { on_track: 'On track', warning: 'At risk', breached: 'Breached', met: 'Met' }

export const slaSummarySchema = z.object({
  response_status: z.enum(METRIC_STATUSES), response_due_at: z.string(),
  resolution_status: z.enum(METRIC_STATUSES), resolution_due_at: z.string(), paused: z.boolean(),
})
export type SLASummary = z.infer<typeof slaSummarySchema>

const eventSchema = z.object({
  id: z.number(), type: z.string(), metric: z.string(), occurred_at: z.string(),
  payload: z.record(z.string(), z.unknown()), actor: z.string().nullable(),
})
export const ticketSLASchema = z.object({
  id: z.string(), policy_name: z.string(), business_hours_name: z.string().nullable(), priority: z.enum(PRIORITIES),
  started_at: z.string(), warning_threshold_pct: z.number(),
  response_minutes: z.number(), response_due_at: z.string(), response_status: z.enum(METRIC_STATUSES),
  responded_at: z.string().nullable(), response_remaining_seconds: z.number().nullable(),
  resolution_minutes: z.number(), resolution_due_at: z.string(), resolution_status: z.enum(METRIC_STATUSES),
  resolved_at: z.string().nullable(), resolution_remaining_seconds: z.number().nullable(),
  paused: z.boolean(), paused_at: z.string().nullable(), paused_seconds: z.number(), escalated_at: z.string().nullable(),
  events: z.array(eventSchema),
})
export type TicketSLA = z.infer<typeof ticketSLASchema>

export const useTicketSLA = (ticketId: string, enabled = true) =>
  useQuery({
    queryKey: ['tickets', 'sla', ticketId],
    queryFn: () => api.get(`/tickets/${ticketId}/sla/`, { schema: ticketSLASchema.nullable() }),
    enabled,
    // Remaining *working* time comes from the server; refresh it regularly (events refresh it sooner).
    refetchInterval: 60_000,
  })

export const targetSchema = z.object({
  priority: z.enum(PRIORITIES), first_response_minutes: z.number(), resolution_minutes: z.number(), warning_threshold_pct: z.number(),
})
export type Target = z.infer<typeof targetSchema>
export const policySchema = z.object({
  id: z.string(), name: z.string(), description: z.string(), is_default: z.boolean(), is_active: z.boolean(),
  business_hours: z.string().nullable(), business_hours_name: z.string().nullable(),
  conditions: z.object({ categories: z.array(z.string()), customer_tiers: z.array(z.string()), channels: z.array(z.string()) }),
  priority_order: z.number(), escalate_on_breach: z.boolean(), targets: z.array(targetSchema),
})
export type Policy = z.infer<typeof policySchema>

export const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
export const WEEKDAY_LABEL: Record<(typeof WEEKDAYS)[number], string> = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' }
export const hoursSchema = z.object({
  id: z.string(), name: z.string(), timezone: z.string(),
  schedule: z.record(z.string(), z.array(z.tuple([z.string(), z.string()]))),
  holidays: z.array(z.object({ date: z.string(), name: z.string() })), policies: z.array(z.string()),
})
export type BusinessHours = z.infer<typeof hoursSchema>

const reportRow = z.object({
  tickets: z.number(), resolution_met: z.number(), resolution_breached: z.number(), resolution_compliance: z.number().nullable(),
  response_met: z.number(), response_breached: z.number(), response_compliance: z.number().nullable(), at_risk: z.number(),
})
export const reportSchema = z.object({
  start: z.string(), end: z.string(), resolution_compliance: z.number().nullable(), by_priority: z.record(z.string(), reportRow),
})

export const usePolicies = () => useQuery({ queryKey: ['sla', 'policies'], queryFn: () => api.get('/sla/policies/', { schema: z.array(policySchema) }) })
export const useBusinessHours = () => useQuery({ queryKey: ['sla', 'hours'], queryFn: () => api.get('/sla/business-hours/', { schema: z.array(hoursSchema) }) })
export const useSLAReport = (days: number) =>
  useQuery({
    queryKey: ['sla', 'report', days],
    queryFn: () => api.get(`/sla/report/${toQuery({ start: new Date(Date.now() - days * 86_400_000).toISOString() })}`, { schema: reportSchema }),
  })

function useSave<T>(path: string, key: string, schema: z.ZodType<T>) {
  const qc = useQueryClient()
  const done = () => { void qc.invalidateQueries({ queryKey: ['sla'] }) }
  return {
    save: useMutation({
      mutationFn: ({ id, ...body }: { id?: string } & Record<string, unknown>) =>
        id ? api.patch(`${path}${id}/`, body, { schema }) : api.post(path, body, { schema }),
      onSuccess: done,
    }),
    remove: useMutation({ mutationFn: (id: string) => api.delete(`${path}${id}/`), onSuccess: done }),
    key,
  }
}
export const usePolicyMutations = () => useSave('/sla/policies/', 'policies', policySchema)
export const useHoursMutations = () => useSave('/sla/business-hours/', 'hours', hoursSchema)
