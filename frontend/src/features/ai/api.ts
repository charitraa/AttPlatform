import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

export const KINDS = ['classification', 'priority', 'routing', 'summary', 'response_suggestion', 'knowledge_answer',
  'insights', 'knowledge_extraction'] as const
export type Kind = (typeof KINDS)[number]

export const analysisSchema = z.object({
  id: z.string(),
  ticket: z.string().nullable(),
  kind: z.enum(KINDS),
  status: z.enum(['pending', 'running', 'completed', 'failed']),
  provider: z.string(),
  model: z.string(),
  prompt_version: z.string(),
  is_mock: z.boolean(),
  input: z.record(z.string(), z.unknown()),
  output: z.record(z.string(), z.any()).nullable(),
  confidence: z.number().nullable(),
  reasoning: z.string(),
  error: z.string(),
  latency_ms: z.number().nullable(),
  tokens_in: z.number().nullable(),
  tokens_out: z.number().nullable(),
  attempts: z.number(),
  trigger: z.string(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
})
export type Analysis = z.infer<typeof analysisSchema>

export const recommendationSchema = z.object({
  id: z.string(),
  type: z.enum(['category', 'priority', 'assignee', 'technician']),
  value: z.record(z.string(), z.any()),
  previous_value: z.record(z.string(), z.any()).nullable(),
  confidence: z.number().nullable(),
  reasoning: z.string(),
  status: z.enum(['pending', 'accepted', 'rejected', 'overridden', 'auto_applied', 'superseded']),
  is_mock: z.boolean(),
  ticket: z.object({ id: z.string(), reference: z.string(), title: z.string() }),
  decided_by: z.string().nullable(),
  decided_at: z.string().nullable(),
  override_value: z.record(z.string(), z.any()).nullable(),
  note: z.string(),
  created_at: z.string(),
})
export type Recommendation = z.infer<typeof recommendationSchema>

const ticketAISchema = z.object({
  analyses: z.array(analysisSchema),
  recommendations: z.array(recommendationSchema),
  ai_enabled: z.boolean(),
})

export const insightSchema = z.object({
  id: z.string(),
  type: z.enum(['recurring_issue', 'pattern', 'sla_risk', 'report']),
  title: z.string(),
  body: z.string(),
  evidence: z.array(z.string()),
  period_start: z.string(),
  period_end: z.string(),
  is_dismissed: z.boolean(),
  is_mock: z.boolean(),
  created_at: z.string(),
})
export type Insight = z.infer<typeof insightSchema>

const statusSchema = z.object({
  provider: z.string(),
  model: z.string(),
  mock_mode: z.boolean(),
  ai_enabled: z.boolean(),
  auto_triage: z.boolean(),
  routing_policy: z.string(),
  auto_apply_min_confidence: z.number(),
  acceptance: z.array(z.object({
    type: z.string(), prompt_version: z.string(), is_mock: z.boolean(), total: z.number(), accepted: z.number(),
    auto_applied: z.number(), overridden: z.number(), rejected: z.number(), pending: z.number(),
    acceptance_rate: z.number().nullable(),
  })).nullable(),
})

const busy = (a: Pick<Analysis, 'status'>) => a.status === 'pending' || a.status === 'running'

export const aiKeys = {
  ticket: (id: string) => ['ai', 'ticket', id] as const,
  assistant: ['ai', 'assistant'] as const,
  insights: (dismissed: boolean) => ['ai', 'insights', dismissed] as const,
  status: ['ai', 'status'] as const,
}

/** Latest analysis per capability + recommendations. Polls while anything is still running. */
export function useTicketAI(ticketId: string, enabled = true) {
  return useQuery({
    queryKey: aiKeys.ticket(ticketId),
    queryFn: () => api.get(`/tickets/${ticketId}/ai/`, { schema: ticketAISchema }),
    enabled,
    refetchInterval: (q) => (q.state.data?.analyses.some(busy) ? 1500 : false),
  })
}

export function useRunTicketAI(ticketId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (kinds: Kind[]) => api.post(`/tickets/${ticketId}/ai/`, { kinds }, { schema: z.array(analysisSchema) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: aiKeys.ticket(ticketId) }),
  })
}

export function useDecide(ticketId?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; decision: 'accept' | 'reject' | 'override'; value?: Record<string, unknown>; note?: string }) =>
      api.post(`/ai/recommendations/${id}/decide/`, body, { schema: recommendationSchema }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['ai'] })
      if (ticketId) void qc.invalidateQueries({ queryKey: ['tickets', 'detail', ticketId] })
      void qc.invalidateQueries({ queryKey: ['tickets', 'list'] })
    },
  })
}

export function useAssistantHistory() {
  return useQuery({
    queryKey: aiKeys.assistant,
    queryFn: () => api.get('/ai/assistant/', { schema: z.array(analysisSchema) }),
    refetchInterval: (q) => (q.state.data?.some(busy) ? 1500 : false),
  })
}

export function useAsk() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (question: string) => api.post('/ai/assistant/', { question }, { schema: analysisSchema }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: aiKeys.assistant }),
  })
}

export function useInsights(dismissed = false) {
  return useQuery({
    queryKey: aiKeys.insights(dismissed),
    queryFn: () => api.get(`/ai/insights/${toQuery({ is_dismissed: dismissed })}`, { schema: paginated(insightSchema) }),
    placeholderData: keepPreviousData,
  })
}

export function useGenerateInsights() {
  return useMutation({
    mutationFn: (days: number) => api.post('/ai/insights/generate/', { days }, { schema: analysisSchema }),
  })
}

export function useDismissInsight() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post(`/ai/insights/${id}/dismiss/`, undefined, { schema: insightSchema }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['ai', 'insights'] }),
  })
}

export function useAIStatus() {
  return useQuery({ queryKey: aiKeys.status, queryFn: () => api.get('/ai/status/', { schema: statusSchema }), staleTime: 60_000 })
}

/**
 * Await a background analysis: polls until it completes or fails (or times out).
 * Used by click handlers ("Suggest reply", "Generate now") instead of effects.
 */
export async function waitForAnalysis(id: string, { intervalMs = 1200, timeoutMs = 120_000 } = {}): Promise<Analysis> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const a = await api.get(`/ai/analyses/${id}/`, { schema: analysisSchema })
    if (!busy(a)) return a
    if (Date.now() > deadline) throw new Error('The AI is taking longer than expected. Try again in a moment.')
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}
