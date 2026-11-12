import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

export const articleSchema = z.object({
  id: z.string(),
  title: z.string(),
  summary: z.string(),
  body: z.string(),
  category: z.string().nullable(),
  category_name: z.string().nullable(),
  tags: z.array(z.string()),
  status: z.enum(['draft', 'in_review', 'published', 'archived']),
  source: z.enum(['manual', 'ai_extracted']),
  source_ticket: z.object({ id: z.string(), reference: z.string(), title: z.string() }).nullable(),
  author: z.string().nullable(),
  reviewed_by: z.string().nullable(),
  published_at: z.string().nullable(),
  helpful_count: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type Article = z.infer<typeof articleSchema>
export type ArticleInput = Partial<Pick<Article, 'title' | 'summary' | 'body' | 'category' | 'tags'>>

export function useArticles(filters: { status?: string; search?: string; page?: number }) {
  return useQuery({
    queryKey: ['knowledge', filters],
    queryFn: () => api.get(`/knowledge/articles/${toQuery({ ...filters })}`, { schema: paginated(articleSchema) }),
    placeholderData: keepPreviousData,
  })
}

export function useSaveArticle(id?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ArticleInput) =>
      id ? api.patch(`/knowledge/articles/${id}/`, data, { schema: articleSchema }) : api.post('/knowledge/articles/', data, { schema: articleSchema }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}

export function useMoveArticle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'submit' | 'publish' | 'return-to-draft' | 'archive' }) =>
      api.post(`/knowledge/articles/${id}/${action}/`, undefined, { schema: articleSchema }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['knowledge'] }),
  })
}
