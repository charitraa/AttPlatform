import { PRIORITY_LABEL, type Priority } from '@/features/tickets/constants'
import type { Recommendation } from './api'

export const TYPE_LABEL: Record<Recommendation['type'], string> = {
  category: 'Category', priority: 'Priority', assignee: 'Agent', technician: 'Technician',
}

export function recommendationValue(r: Pick<Recommendation, 'type' | 'value'>, v = r.value): string {
  if (r.type === 'priority') return PRIORITY_LABEL[v.priority as Priority] ?? String(v.priority)
  return String(v.name ?? v.category_id ?? v.user_id ?? '—')
}
