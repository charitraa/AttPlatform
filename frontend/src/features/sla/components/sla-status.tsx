import { CheckCircle2, CircleAlert, Clock, Pause, TriangleAlert } from 'lucide-react'
import { formatDateTime, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { METRIC_LABEL, type MetricStatus, type SLASummary } from '../api'

const TONE: Record<MetricStatus, string> = {
  on_track: 'border-success/40 text-success',
  warning: 'border-warning/50 text-warning',
  breached: 'border-destructive/50 text-destructive',
  met: 'border-border text-muted-foreground',
}
const ICON = { on_track: Clock, warning: TriangleAlert, breached: CircleAlert, met: CheckCircle2 }

export function MetricPill({ status, className }: { status: MetricStatus; className?: string }) {
  const Icon = ICON[status]
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium', TONE[status], className)}>
      <Icon className="size-3" aria-hidden /> {METRIC_LABEL[status]}
    </span>
  )
}

/** The ticket list's SLA cell: the metric that needs attention first, with its deadline. */
export function SLAChip({ sla }: { sla: SLASummary }) {
  const responseOpen = sla.response_status !== 'met'
  const order: MetricStatus[] = ['breached', 'warning', 'on_track', 'met']
  const response = { label: 'Response', status: sla.response_status, due: sla.response_due_at }
  const resolution = { label: 'Resolution', status: sla.resolution_status, due: sla.resolution_due_at }
  const pick = responseOpen && order.indexOf(response.status) <= order.indexOf(resolution.status) ? response : resolution
  if (sla.paused && pick === resolution && resolution.status !== 'breached') {
    return <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Pause className="size-3" aria-hidden /> Paused</span>
  }
  if (pick.status === 'met') return <MetricPill status="met" />
  return (
    <span className="inline-flex flex-col gap-0.5" title={`${pick.label} due ${formatDateTime(pick.due)}`}>
      <MetricPill status={pick.status} className="self-start" />
      <span className="text-xs text-muted-foreground">{pick.label} due {formatRelative(pick.due)}</span>
    </span>
  )
}
