import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

export const assetSchema = z.object({
  id: z.string(),
  asset_tag: z.string(),
  name: z.string(),
  customer: z.string(),
  customer_name: z.string(),
  category: z.string().nullable(),
  category_name: z.string().nullable(),
  manufacturer: z.string(),
  model: z.string(),
  serial_number: z.string(),
  location: z.string(),
  installed_at: z.string().nullable(),
  warranty_expires_at: z.string().nullable(),
  under_warranty: z.boolean(),
  status: z.enum(['active', 'in_repair', 'retired']),
  purchase_cost: z.string().nullable(),
  currency: z.string(),
  notes: z.string(),
  open_ticket_count: z.number().optional(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type Asset = z.infer<typeof assetSchema>

export const assetCategorySchema = z.object({ id: z.string(), name: z.string() })

export interface AssetFilters { search?: string; customer?: string; status?: string; warranty?: string; page?: number; page_size?: number }

export function useAssets(filters: AssetFilters, enabled = true) {
  return useQuery({
    queryKey: ['assets', 'list', filters],
    queryFn: () => api.get(`/assets/${toQuery({ ...filters })}`, { schema: paginated(assetSchema) }),
    placeholderData: keepPreviousData,
    enabled,
  })
}

export function useAssetCategories() {
  return useQuery({ queryKey: ['asset-categories'], queryFn: () => api.get('/asset-categories/', { schema: z.array(assetCategorySchema) }) })
}

export type AssetInput = Partial<Pick<Asset, 'asset_tag' | 'name' | 'customer' | 'category' | 'manufacturer' | 'model' | 'serial_number' | 'location' | 'installed_at' | 'warranty_expires_at' | 'status' | 'purchase_cost' | 'currency' | 'notes'>>

export function useSaveAsset(id?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: AssetInput) =>
      id ? api.patch(`/assets/${id}/`, data, { schema: assetSchema }) : api.post('/assets/', data, { schema: assetSchema }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['assets'] }),
  })
}
