import { AlertTriangle, ArrowDown, ArrowUp, Minus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { PRIORITY_LABEL, STATUS_LABEL, type Priority, type TicketStatus } from '../constants'

// Text label always present; colour only reinforces it.
const STATUS_STYLE: Record<TicketStatus, string> = {
  new: 'border-primary/40 text-primary',
  open: 'border-primary/40 text-primary',
  reopened: 'border-primary/40 text-primary',
  assigned: 'border-border text-foreground',
  in_progress: 'border-series-1/50 bg-series-1/10 text-foreground',
  pending_customer: 'border-warning/50 text-foreground',
  pending_parts: 'border-warning/50 text-foreground',
  escalated: 'border-destructive/50 bg-destructive/10 text-destructive',
  resolved: 'border-success/50 text-success',
  closed: 'border-border text-muted-foreground',
}

export function StatusBadge({ status, className }: { status: TicketStatus; className?: string }) {
  return <Badge variant="outline" className={cn('whitespace-nowrap', STATUS_STYLE[status], className)}>{STATUS_LABEL[status]}</Badge>
}

const PRIORITY_ICON = { low: ArrowDown, medium: Minus, high: ArrowUp, critical: AlertTriangle }
const PRIORITY_STYLE: Record<Priority, string> = {
  low: 'text-muted-foreground',
  medium: 'text-foreground',
  high: 'text-warning',
  critical: 'text-destructive font-medium',
}

export function PriorityLabel({ priority, className }: { priority: Priority; className?: string }) {
  const Icon = PRIORITY_ICON[priority]
  return (
    <span className={cn('inline-flex items-center gap-1 text-sm whitespace-nowrap', PRIORITY_STYLE[priority], className)}>
      <Icon className="size-3.5" aria-hidden /> {PRIORITY_LABEL[priority]}
    </span>
  )
}
