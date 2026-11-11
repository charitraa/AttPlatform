import type { HistoryEntry } from './api'
import { PRIORITY_LABEL, STATUS_LABEL, type Priority, type TicketStatus } from './constants'

const FIELD_LABEL: Record<string, string> = {
  title: 'title', description: 'description', priority: 'priority', category: 'category', tags: 'tags',
  contact: 'contact', asset: 'asset', resolution_notes: 'resolution notes', assigned_agent: 'agent',
  assigned_technician: 'technician',
}

function label(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'none'
  if (typeof value === 'object' && value && 'label' in value) return String((value as { label: string }).label)
  if (Array.isArray(value)) return value.join(', ') || 'none'
  const s = String(value)
  return STATUS_LABEL[s as TicketStatus] ?? PRIORITY_LABEL[s as Priority] ?? s
}

/** One human sentence per history entry. Exported for the dashboard activity feed. */
export function describeEvent(e: Pick<HistoryEntry, 'event' | 'field' | 'old_value' | 'new_value'>): string {
  switch (e.event) {
    case 'created': return 'created the ticket'
    case 'status_changed': return `changed status from ${label(e.old_value)} to ${label(e.new_value)}`
    case 'assigned':
      return e.new_value ? `assigned the ${FIELD_LABEL[e.field] ?? e.field} to ${label(e.new_value)}` : `removed the ${FIELD_LABEL[e.field] ?? e.field}`
    case 'commented': {
      const internal = (e.new_value as { visibility?: string } | null)?.visibility === 'internal'
      return internal ? 'added an internal note' : 'replied'
    }
    case 'attachment_added': return `attached ${(e.new_value as { name?: string } | null)?.name ?? 'a file'}`
    case 'archived': return 'archived the ticket'
    case 'unarchived': return 'unarchived the ticket'
    case 'field_changed':
      if (e.field === 'description' || e.field === 'resolution_notes') return `updated the ${FIELD_LABEL[e.field]}`
      return `changed ${FIELD_LABEL[e.field] ?? e.field} from ${label(e.old_value)} to ${label(e.new_value)}`
    default: return e.event.replaceAll('_', ' ')
  }
}
