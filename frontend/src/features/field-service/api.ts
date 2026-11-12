import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

export const WO_STATUSES = ['created', 'assigned', 'accepted', 'en_route', 'on_site', 'in_progress', 'completed', 'cancelled'] as const
export type WOStatus = (typeof WO_STATUSES)[number]
export const WO_STATUS_LABEL: Record<WOStatus, string> = {
  created: 'Created', assigned: 'Assigned', accepted: 'Accepted', en_route: 'En route', on_site: 'On site',
  in_progress: 'In progress', completed: 'Completed', cancelled: 'Cancelled',
}
export const STEP_LABEL: Record<string, string> = {
  accepted: 'Accept job', en_route: 'Start travelling', on_site: 'Arrived on site', in_progress: 'Start work',
  completed: 'Complete job', cancelled: 'Cancel work order',
}
export const TECH_STATUS_LABEL = { available: 'Available', busy: 'On a job', off_duty: 'Off duty', on_leave: 'On leave' } as const

const userRef = z.object({ id: z.string(), full_name: z.string(), email: z.string() })
const techRef = z.object({ id: z.string(), user_id: z.string(), name: z.string() })

export const workOrderListSchema = z.object({
  id: z.string(), number: z.number(), reference: z.string(), title: z.string(), status: z.enum(WO_STATUSES),
  priority: z.string(), customer: z.object({ id: z.string(), name: z.string() }), technician: techRef.nullable(),
  ticket: z.object({ id: z.string(), reference: z.string() }).nullable(), service_address: z.string(),
  scheduled_start: z.string().nullable(), scheduled_end: z.string().nullable(), customer_confirmed_at: z.string().nullable(),
  created_at: z.string(), updated_at: z.string(),
})
export type WorkOrderListItem = z.infer<typeof workOrderListSchema>

export const workOrderSchema = workOrderListSchema.extend({
  description: z.string(),
  asset: z.object({ id: z.string(), asset_tag: z.string(), name: z.string(), serial_number: z.string() }).nullable(),
  lat: z.string().nullable(), lng: z.string().nullable(),
  actual_start: z.string().nullable(), actual_end: z.string().nullable(),
  service_notes: z.string(), completion_summary: z.string(),
  parts_used: z.array(z.object({ name: z.string(), quantity: z.number(), unit_cost: z.string().nullable().optional() })),
  labor_minutes: z.number().nullable(), labor_cost: z.string().nullable(), parts_cost: z.string().nullable(), currency: z.string(),
  customer_signed_by: z.string(), customer_rating: z.number().nullable(), customer_comment: z.string(),
  cancelled_reason: z.string(), created_by: userRef.nullable(),
  next_steps: z.array(z.string()),
  capabilities: z.object({ edit: z.boolean(), assign: z.boolean(), schedule: z.boolean(), decline: z.boolean(), add_evidence: z.boolean(), confirm: z.boolean() }),
  appointment: z.object({ id: z.string(), starts_at: z.string(), ends_at: z.string(), notes: z.string() }).nullable(),
  warnings: z.array(z.string()).optional(),
})
export type WorkOrder = z.infer<typeof workOrderSchema>

export const evidenceSchema = z.object({
  id: z.string(), kind: z.enum(['before_photo', 'after_photo', 'document', 'signature', 'other']), original_name: z.string(),
  content_type: z.string(), size_bytes: z.number(), sha256: z.string(), caption: z.string(), uploaded_by: userRef.nullable(),
  created_at: z.string(), download_url: z.string(),
})
export type Evidence = z.infer<typeof evidenceSchema>

const statusLogSchema = z.object({
  id: z.number(), from_status: z.string(), to_status: z.string(), actor: userRef.nullable(), note: z.string(),
  lat: z.string().nullable(), lng: z.string().nullable(), created_at: z.string(),
})

export const technicianSchema = z.object({
  id: z.string(),
  user: z.object({ id: z.string(), full_name: z.string(), email: z.string(), phone: z.string() }),
  employee_id: z.string(), status: z.enum(['available', 'busy', 'off_duty', 'on_leave']),
  home_lat: z.string().nullable(), home_lng: z.string().nullable(), max_daily_jobs: z.number(),
  hourly_cost: z.string().nullable(), currency: z.string(), location_sharing_enabled: z.boolean(), notes: z.string(),
  service_areas: z.array(z.string()), skills: z.array(z.object({ skill: z.string(), name: z.string(), level: z.number() })),
  active_jobs: z.number(), jobs_today: z.number(), created_at: z.string(),
})
export type Technician = z.infer<typeof technicianSchema>

export const skillSchema = z.object({ id: z.string(), name: z.string(), category: z.string(), ticket_categories: z.array(z.string()) })
export const areaSchema = z.object({ id: z.string(), name: z.string(), description: z.string(), cities: z.array(z.string()) })
export const certSchema = z.object({ id: z.string(), name: z.string(), issuer: z.string(), number: z.string(), issued_at: z.string().nullable(), expires_at: z.string().nullable(), is_expired: z.boolean() })
export const availabilitySchema = z.object({ id: z.string(), type: z.enum(['shift', 'time_off']), starts_at: z.string(), ends_at: z.string(), note: z.string() })
export type Availability = z.infer<typeof availabilitySchema>

export const candidateSchema = z.object({
  technician_id: z.string(), user_id: z.string(), name: z.string(), status: z.string(), score: z.number(),
  factors: z.record(z.string(), z.number()), active_jobs: z.number(), distance_km: z.number().nullable(),
  matched_skills: z.array(z.string()), missing_skills: z.array(z.string()), blocked_reason: z.string(),
})
export type Candidate = z.infer<typeof candidateSchema>

export const appointmentSchema = z.object({
  id: z.string(),
  work_order: z.object({ id: z.string(), reference: z.string(), title: z.string(), status: z.string(), priority: z.string(), customer: z.string(), service_address: z.string() }),
  technician: z.object({ id: z.string(), name: z.string() }),
  starts_at: z.string(), ends_at: z.string(), status: z.string(), notes: z.string(),
})
export type Appointment = z.infer<typeof appointmentSchema>
const scheduleSchema = z.object({
  technicians: z.array(z.object({ id: z.string(), name: z.string(), status: z.string() })),
  appointments: z.array(appointmentSchema),
  availability: z.array(z.object({ id: z.string(), technician_id: z.string(), type: z.string(), starts_at: z.string(), ends_at: z.string(), note: z.string() })),
})
export type ScheduleData = z.infer<typeof scheduleSchema>

export interface WOFilters { search?: string; status?: string; technician?: string; ticket?: string; customer?: string; ordering?: string; page?: number }

export function useWorkOrders(f: WOFilters, enabled = true) {
  return useQuery({
    queryKey: ['work-orders', 'list', f],
    queryFn: () => api.get(`/work-orders/${toQuery({ ...f })}`, { schema: paginated(workOrderListSchema) }),
    placeholderData: keepPreviousData,
    enabled,
  })
}
export const useWorkOrder = (id: string) =>
  useQuery({ queryKey: ['work-orders', 'detail', id], queryFn: () => api.get(`/work-orders/${id}/`, { schema: workOrderSchema }) })
export const useEvidence = (id: string) =>
  useQuery({ queryKey: ['work-orders', 'detail', id, 'evidence'], queryFn: () => api.get(`/work-orders/${id}/evidence/`, { schema: z.array(evidenceSchema) }) })
export const useStatusLog = (id: string) =>
  useQuery({ queryKey: ['work-orders', 'detail', id, 'log'], queryFn: () => api.get(`/work-orders/${id}/status-log/`, { schema: z.array(statusLogSchema) }) })
export const useSuggestions = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: ['work-orders', 'detail', id, 'suggestions'],
    queryFn: () => api.get(`/work-orders/${id}/suggest-technicians/`, { schema: z.object({ weights: z.record(z.string(), z.number()), candidates: z.array(candidateSchema) }) }),
    enabled,
  })

/** All work-order mutations return the fresh work order. */
function useWOMutation<V>(id: string, fn: (v: V) => Promise<WorkOrder>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (wo) => {
      qc.setQueryData(['work-orders', 'detail', id], wo)
      void qc.invalidateQueries({ queryKey: ['work-orders'] })
      void qc.invalidateQueries({ queryKey: ['schedule'] })
      void qc.invalidateQueries({ queryKey: ['technicians'] })
    },
  })
}
export const useAssignWO = (id: string) => useWOMutation(id, (technician: string | null) => api.post(`/work-orders/${id}/assign/`, { technician }, { schema: workOrderSchema }))
export const useAdvance = (id: string) => useWOMutation(id, (body: Record<string, unknown>) => api.post(`/work-orders/${id}/advance/`, body, { schema: workOrderSchema }))
export const useDecline = (id: string) => useWOMutation(id, (reason: string) => api.post(`/work-orders/${id}/decline/`, { reason }, { schema: workOrderSchema }))
export const useCancelWO = (id: string) => useWOMutation(id, (reason: string) => api.post(`/work-orders/${id}/cancel/`, { reason }, { schema: workOrderSchema }))
export const useConfirmWO = (id: string) => useWOMutation(id, (body: { signed_by: string; rating?: number | null; comment?: string }) => api.post(`/work-orders/${id}/confirm/`, body, { schema: workOrderSchema }))
export const useScheduleWO = (id: string) => useWOMutation(id, (body: { starts_at: string; ends_at: string; notes?: string }) => api.post(`/work-orders/${id}/schedule/`, body, { schema: workOrderSchema }))
export const useUpdateWO = (id: string) => useWOMutation(id, (body: Record<string, unknown>) => api.patch(`/work-orders/${id}/`, body, { schema: workOrderSchema }))

export function useCreateWO() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post('/work-orders/', body, { schema: workOrderSchema }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['work-orders'] }),
  })
}

export function useUploadEvidence(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, kind, caption }: { file: File; kind: Evidence['kind']; caption?: string }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('kind', kind)
      if (caption) form.append('caption', caption)
      return api.post(`/work-orders/${id}/evidence/`, form, { schema: evidenceSchema })
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['work-orders', 'detail', id, 'evidence'] }),
  })
}

export function useTechnicians(filters: { search?: string; status?: string } = {}) {
  return useQuery({
    queryKey: ['technicians', 'list', filters],
    queryFn: () => api.get(`/technicians/${toQuery({ ...filters, page_size: 100 })}`, { schema: paginated(technicianSchema) }),
    placeholderData: keepPreviousData,
  })
}
export const useTechnician = (id: string) =>
  useQuery({ queryKey: ['technicians', 'detail', id], queryFn: () => api.get(`/technicians/${id}/`, { schema: technicianSchema }) })
export const useMyTechnician = (enabled = true) =>
  useQuery({ queryKey: ['technicians', 'me'], queryFn: () => api.get('/technicians/me/', { schema: technicianSchema }), enabled })
export const useSkills = () => useQuery({ queryKey: ['skills'], queryFn: () => api.get('/skills/', { schema: z.array(skillSchema) }), staleTime: 60_000 })
export const useAreas = () => useQuery({ queryKey: ['service-areas'], queryFn: () => api.get('/service-areas/', { schema: z.array(areaSchema) }), staleTime: 60_000 })
export const useCerts = (id: string) => useQuery({ queryKey: ['technicians', 'detail', id, 'certs'], queryFn: () => api.get(`/technicians/${id}/certifications/`, { schema: z.array(certSchema) }) })
export const useAvailability = (id: string) => useQuery({ queryKey: ['technicians', 'detail', id, 'availability'], queryFn: () => api.get(`/technicians/${id}/availability/`, { schema: z.array(availabilitySchema) }) })

export function useTechMutation() {
  const qc = useQueryClient()
  const done = () => void qc.invalidateQueries({ queryKey: ['technicians'] })
  return {
    update: useMutation({ mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) => api.patch(`/technicians/${id}/`, body, { schema: technicianSchema }), onSuccess: done }),
    setSkills: useMutation({ mutationFn: ({ id, skills }: { id: string; skills: { skill: string; level: number }[] }) => api.put(`/technicians/${id}/skills/`, skills), onSuccess: done }),
    addCert: useMutation({ mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) => api.post(`/technicians/${id}/certifications/`, body, { schema: certSchema }), onSuccess: done }),
    removeCert: useMutation({ mutationFn: ({ id, certId }: { id: string; certId: string }) => api.delete(`/technicians/${id}/certifications/${certId}/`), onSuccess: done }),
    addAvailability: useMutation({ mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) => api.post(`/technicians/${id}/availability/`, body, { schema: availabilitySchema }), onSuccess: () => { done(); void qc.invalidateQueries({ queryKey: ['schedule'] }) } }),
    removeAvailability: useMutation({ mutationFn: ({ id, entryId }: { id: string; entryId: string }) => api.delete(`/technicians/${id}/availability/${entryId}/`), onSuccess: () => { done(); void qc.invalidateQueries({ queryKey: ['schedule'] }) } }),
    updateMe: useMutation({ mutationFn: (body: { status?: string; location_sharing_enabled?: boolean }) => api.patch('/technicians/me/', body, { schema: technicianSchema }), onSuccess: done }),
  }
}

export function useSchedule(start: Date, end: Date) {
  return useQuery({
    queryKey: ['schedule', start.toISOString(), end.toISOString()],
    queryFn: () => api.get(`/schedule/${toQuery({ start: start.toISOString(), end: end.toISOString() })}`, { schema: scheduleSchema }),
    placeholderData: keepPreviousData,
  })
}

export function reportLocation(body: { lat: number; lng: number; accuracy_m?: number }) {
  return api.post('/technicians/me/location/', { lat: body.lat.toFixed(6), lng: body.lng.toFixed(6), accuracy_m: body.accuracy_m ? Math.round(body.accuracy_m) : null })
}
