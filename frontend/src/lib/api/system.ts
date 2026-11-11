import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from './client'

const dependencyCheck = z.object({ status: z.enum(['ok', 'error']), latency_ms: z.number() })

export const healthSchema = z.object({ status: z.string(), version: z.string(), timestamp: z.string() })
export const readinessSchema = z.object({ status: z.enum(['ok', 'degraded']), checks: z.record(z.string(), dependencyCheck) })
export const metaSchema = z.object({
  name: z.string(),
  version: z.string(),
  environment: z.string(),
  ai_provider: z.string(),
  ai_mock_mode: z.boolean(),
  features: z.record(z.string(), z.boolean()),
})

export type Health = z.infer<typeof healthSchema>
export type Readiness = z.infer<typeof readinessSchema>
export type Meta = z.infer<typeof metaSchema>

export const systemKeys = {
  health: ['system', 'health'] as const,
  readiness: ['system', 'readiness'] as const,
  meta: ['system', 'meta'] as const,
}

export const fetchHealth = () => api.get('/health/', { schema: healthSchema })
// 503 still carries a valid body describing which dependency failed.
export const fetchReadiness = () => api.get('/health/ready/', { schema: readinessSchema, acceptStatus: [503] })
export const fetchMeta = () => api.get('/meta/', { schema: metaSchema })

export function useHealth() {
  return useQuery({ queryKey: systemKeys.health, queryFn: fetchHealth, refetchInterval: 30_000 })
}
export function useReadiness() {
  return useQuery({ queryKey: systemKeys.readiness, queryFn: fetchReadiness, refetchInterval: 30_000 })
}
export function useMeta() {
  return useQuery({ queryKey: systemKeys.meta, queryFn: fetchMeta, staleTime: 5 * 60_000 })
}
