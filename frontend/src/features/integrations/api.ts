import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

const fieldSchema = z.object({ name: z.string(), label: z.string(), required: z.boolean(), help: z.string(), kind: z.string(), choices: z.array(z.string()) })
export type ConnectorField = z.infer<typeof fieldSchema>
const connectorSchema = z.object({
  kind: z.string(), provider: z.string(), label: z.string(), description: z.string(), fields: z.array(fieldSchema),
  secrets: z.array(fieldSchema), generated_secrets: z.array(z.string()), can_send: z.boolean(), receives: z.boolean(),
})
export type Connector = z.infer<typeof connectorSchema>
const catalogSchema = z.object({ connectors: z.array(connectorSchema), events: z.array(z.object({ type: z.string(), label: z.string() })) })

export const integrationSchema = z.object({
  id: z.string(), kind: z.string(), provider: z.string(), label: z.string(), name: z.string(),
  config: z.record(z.string(), z.unknown()), is_enabled: z.boolean(), health: z.enum(['unknown', 'ok', 'error']),
  last_success_at: z.string().nullable(), last_error_at: z.string().nullable(), last_error: z.string(),
  credentials: z.record(z.string(), z.object({ configured: z.boolean(), hint: z.string() })),
  inbound_url: z.string().nullable(), endpoint_count: z.number().nullable(), created_at: z.string(), updated_at: z.string(),
  generated_secrets: z.record(z.string(), z.string()).optional(),
})
export type Integration = z.infer<typeof integrationSchema>

export const endpointSchema = z.object({
  id: z.string(), url: z.string(), events: z.array(z.string()), is_active: z.boolean(), description: z.string(),
  stats: z.object({ failed: z.number(), last_status: z.string().nullable(), last_at: z.string().nullable() }),
  created_at: z.string(), signing_secret: z.string().optional(),
})
export type Endpoint = z.infer<typeof endpointSchema>
const deliverySchema = z.object({
  id: z.string(), event_id: z.string(), event_type: z.string(), url: z.string(), status: z.enum(['pending', 'succeeded', 'retrying', 'failed']),
  attempts: z.number(), next_retry_at: z.string().nullable(), response_code: z.number().nullable(), response_body: z.string(),
  error: z.string(), delivered_at: z.string().nullable(), payload: z.unknown(), created_at: z.string(),
})
export type Delivery = z.infer<typeof deliverySchema>
const logSchema = z.object({
  id: z.number(), direction: z.string(), operation: z.string(), status: z.enum(['ok', 'error']), duration_ms: z.number().nullable(),
  request_summary: z.string(), response_summary: z.string(), error: z.string(), created_at: z.string(),
})
const inboundSchema = z.object({
  id: z.string(), external_id: z.string(), status: z.string(), result: z.record(z.string(), z.unknown()), error: z.string(),
  payload: z.unknown(), created_at: z.string(), processed_at: z.string().nullable(),
})
export type InboundEvent = z.infer<typeof inboundSchema>
const resultSchema = z.object({ ok: z.boolean(), message: z.string() })

export const useCatalog = () => useQuery({ queryKey: ['integrations', 'catalog'], queryFn: () => api.get('/integrations/catalog/', { schema: catalogSchema }), staleTime: Infinity })
export const useIntegrations = () => useQuery({ queryKey: ['integrations', 'list'], queryFn: () => api.get('/integrations/', { schema: z.array(integrationSchema) }) })
export const useIntegration = (id: string) => useQuery({ queryKey: ['integrations', id], queryFn: () => api.get(`/integrations/${id}/`, { schema: integrationSchema }) })
export const useEndpoints = (id: string, enabled: boolean) =>
  useQuery({ queryKey: ['integrations', id, 'endpoints'], queryFn: () => api.get(`/integrations/${id}/endpoints/`, { schema: z.array(endpointSchema) }), enabled })
export const useDeliveries = (id: string, f: { status?: string; page?: number }, enabled: boolean) =>
  useQuery({ queryKey: ['integrations', id, 'deliveries', f], queryFn: () => api.get(`/integrations/${id}/deliveries/${toQuery({ ...f })}`, { schema: paginated(deliverySchema) }), enabled, placeholderData: keepPreviousData })
export const useInboundEvents = (id: string, page: number, enabled: boolean) =>
  useQuery({ queryKey: ['integrations', id, 'inbound', page], queryFn: () => api.get(`/integrations/${id}/inbound-events/${toQuery({ page })}`, { schema: paginated(inboundSchema) }), enabled, placeholderData: keepPreviousData })
export const useLogs = (id: string, page: number) =>
  useQuery({ queryKey: ['integrations', id, 'logs', page], queryFn: () => api.get(`/integrations/${id}/logs/${toQuery({ page })}`, { schema: paginated(logSchema) }), placeholderData: keepPreviousData })

export function useIntegrationMutations(id = '') {
  const qc = useQueryClient()
  const refresh = () => void qc.invalidateQueries({ queryKey: ['integrations'] })
  return {
    create: useMutation({ mutationFn: (body: Record<string, unknown>) => api.post('/integrations/', body, { schema: integrationSchema }), onSuccess: refresh }),
    update: useMutation({ mutationFn: (body: Record<string, unknown>) => api.patch(`/integrations/${id}/`, body, { schema: integrationSchema }), onSuccess: refresh }),
    remove: useMutation({ mutationFn: () => api.delete(`/integrations/${id}/`), onSuccess: refresh }),
    test: useMutation({ mutationFn: () => api.post(`/integrations/${id}/test/`, {}, { schema: resultSchema }), onSuccess: refresh }),
    sendTest: useMutation({ mutationFn: (body: { to: string; text?: string; template?: string }) => api.post(`/integrations/${id}/send-test/`, body), onSuccess: refresh }),
    rotate: useMutation({ mutationFn: () => api.post(`/integrations/${id}/rotate-secret/`, {}, { schema: z.object({ signing_secret: z.string() }) }) }),
    addEndpoint: useMutation({ mutationFn: (body: { url: string; events: string[]; description?: string }) => api.post(`/integrations/${id}/endpoints/`, body, { schema: endpointSchema }), onSuccess: refresh }),
    updateEndpoint: useMutation({ mutationFn: ({ endpointId, ...body }: { endpointId: string } & Record<string, unknown>) => api.patch(`/webhook-endpoints/${endpointId}/`, body, { schema: endpointSchema }), onSuccess: refresh }),
    removeEndpoint: useMutation({ mutationFn: (endpointId: string) => api.delete(`/webhook-endpoints/${endpointId}/`), onSuccess: refresh }),
    rotateEndpoint: useMutation({ mutationFn: (endpointId: string) => api.post(`/webhook-endpoints/${endpointId}/rotate-secret/`, {}, { schema: z.object({ signing_secret: z.string() }) }) }),
    redeliver: useMutation({ mutationFn: (deliveryId: string) => api.post(`/webhook-deliveries/${deliveryId}/redeliver/`, {}, { schema: deliverySchema }), onSuccess: refresh }),
  }
}
