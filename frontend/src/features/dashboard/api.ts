import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { PRIORITIES, STATUSES } from '@/features/tickets/constants'

const summarySchema = z.object({
  period_days: z.number(),
  total: z.number(),
  open: z.number(),
  new: z.number(),
  in_progress: z.number(),
  resolved: z.number(),
  closed: z.number(),
  overdue: z.number(),
  critical_open: z.number(),
  unassigned_open: z.number(),
  created_in_period: z.number(),
  resolved_in_period: z.number(),
  avg_resolution_hours: z.number().nullable(),
  avg_first_response_hours: z.number().nullable(),
  sla_compliance: z.number().nullable(),
  technicians_available: z.number().nullable(),
  active_work_orders: z.number().nullable(),
  unavailable: z.record(z.string(), z.string()),
  generated_at: z.string(),
})
export type Summary = z.infer<typeof summarySchema>

const trendsSchema = z.object({ days: z.array(z.object({ date: z.string(), created: z.number(), resolved: z.number() })) })
const breakdownSchema = z.object({
  status: z.array(z.object({ status: z.enum(STATUSES), label: z.string(), count: z.number() })),
  priority: z.array(z.object({ priority: z.enum(PRIORITIES), label: z.string(), count: z.number() })),
  category: z.array(z.object({ category: z.string(), count: z.number() })),
})
const workloadSchema = z.object({
  agents: z.array(z.object({ user_id: z.string(), name: z.string(), open: z.number(), resolved: z.number(), avg_resolution_hours: z.number().nullable() })),
})
const activitySchema = z.object({
  events: z.array(z.object({
    id: z.number(), event: z.string(), field: z.string(), old_value: z.unknown(), new_value: z.unknown(), actor: z.string(),
    ticket: z.object({ id: z.string(), reference: z.string(), title: z.string() }), created_at: z.string(),
  })),
})
export type ActivityEvent = z.infer<typeof activitySchema>['events'][number]

export const useSummary = (days: number) =>
  useQuery({ queryKey: ['dashboard', 'summary', days], queryFn: () => api.get(`/dashboard/summary/?days=${days}`, { schema: summarySchema }) })
export const useTrends = (days: number) =>
  useQuery({ queryKey: ['dashboard', 'trends', days], queryFn: () => api.get(`/dashboard/trends/?days=${days}`, { schema: trendsSchema }) })
export const useBreakdown = () =>
  useQuery({ queryKey: ['dashboard', 'breakdown'], queryFn: () => api.get('/dashboard/breakdown/', { schema: breakdownSchema }) })
export const useWorkload = (days: number, enabled: boolean) =>
  useQuery({ queryKey: ['dashboard', 'workload', days], queryFn: () => api.get(`/dashboard/workload/?days=${days}`, { schema: workloadSchema }), enabled })
export const useActivity = () =>
  useQuery({ queryKey: ['dashboard', 'activity'], queryFn: () => api.get('/dashboard/activity/', { schema: activitySchema }) })
