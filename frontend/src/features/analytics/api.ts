import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { api, apiBlob, saveBlob } from '@/lib/api/client'
import { env } from '@/lib/env'
import { toQuery } from '@/lib/api/pagination'

export const REPORTS = [
  { name: 'ticket_volume', label: 'Ticket volume' },
  { name: 'tickets_by_category', label: 'By category' },
  { name: 'agent_performance', label: 'Agents' },
  { name: 'sla_compliance', label: 'SLA compliance' },
  { name: 'field_service', label: 'Field service' },
  { name: 'customer_satisfaction', label: 'Satisfaction' },
  { name: 'ai_accuracy', label: 'AI accuracy' },
] as const
export type ReportName = (typeof REPORTS)[number]['name']

const columnSchema = z.object({ key: z.string(), label: z.string(), kind: z.enum(['text', 'number', 'hours', 'percent', 'date']) })
export type ReportColumn = z.infer<typeof columnSchema>
export const reportSchema = z.object({
  name: z.string(), title: z.string(), description: z.string(), start: z.string(), end: z.string(),
  columns: z.array(columnSchema), rows: z.array(z.record(z.string(), z.union([z.string(), z.number(), z.null()]))),
})
export type Report = z.infer<typeof reportSchema>

export function useReport(name: ReportName, start: string, end: string) {
  return useQuery({
    queryKey: ['analytics', name, start, end],
    queryFn: () => api.get(`/analytics/reports/${name}/${toQuery({ start, end })}`, { schema: reportSchema }),
    placeholderData: keepPreviousData,
  })
}

export async function downloadReport(name: ReportName, start: string, end: string) {
  const blob = await apiBlob(`${env.apiBaseUrl}/analytics/reports/${name}/${toQuery({ start, end, export: 'csv' })}`)
  saveBlob(blob, `${name}_${start}_${end}.csv`)
}
