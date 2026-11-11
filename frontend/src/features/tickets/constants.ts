export const STATUSES = [
  'new', 'open', 'assigned', 'in_progress', 'pending_customer', 'pending_parts', 'escalated', 'resolved', 'closed', 'reopened',
] as const
export type TicketStatus = (typeof STATUSES)[number]

export const STATUS_LABEL: Record<TicketStatus, string> = {
  new: 'New', open: 'Open', assigned: 'Assigned', in_progress: 'In progress', pending_customer: 'Pending customer',
  pending_parts: 'Pending parts', escalated: 'Escalated', resolved: 'Resolved', closed: 'Closed', reopened: 'Reopened',
}

// Verb phrases for transition buttons.
export const TRANSITION_LABEL: Record<TicketStatus, string> = {
  new: 'Mark as new', open: 'Mark open', assigned: 'Mark assigned', in_progress: 'Start work',
  pending_customer: 'Wait for customer', pending_parts: 'Wait for parts', escalated: 'Escalate', resolved: 'Resolve',
  closed: 'Close', reopened: 'Reopen',
}

export const PRIORITIES = ['low', 'medium', 'high', 'critical'] as const
export type Priority = (typeof PRIORITIES)[number]
export const PRIORITY_LABEL: Record<Priority, string> = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' }

export const CHANNELS = ['staff', 'phone', 'email', 'portal', 'whatsapp', 'api'] as const
export const CHANNEL_LABEL: Record<(typeof CHANNELS)[number], string> = {
  staff: 'Staff', phone: 'Phone', email: 'Email', portal: 'Customer portal', whatsapp: 'WhatsApp', api: 'API',
}

export const ACTIVE_STATUSES: TicketStatus[] = STATUSES.filter((s) => s !== 'resolved' && s !== 'closed')
