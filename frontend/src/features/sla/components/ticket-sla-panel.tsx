import { Pause } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { type MetricStatus, type TicketSLA, useTicketSLA } from '../api'
import { formatDuration, minutesLabel } from '../format'
import { MetricPill } from './sla-status'

const EVENT_LABEL: Record<string, string> = {
  applied: 'SLA applied', recalculated: 'Targets recalculated (priority changed)', warning: 'At risk', breached: 'Breached',
  paused: 'Clock paused', resumed: 'Clock resumed', met: 'Target met', escalated: 'Escalated automatically',
}

/** Re-render every `ms` while `active`, so 24/7 countdowns tick between server refreshes. */
function useTick(active: boolean, ms = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [active, ms])
  return now
}

function Metric({ label, status, due, targetMinutes, remaining, done, paused }: {
  label: string; status: MetricStatus; due: string; targetMinutes: number; remaining: number | null; done: string | null; paused?: boolean
}) {
  const total = targetMinutes * 60
  const used = remaining === null ? 1 : Math.min(1, Math.max(0, 1 - remaining / total))
  const bar = { on_track: 'bg-success', warning: 'bg-warning', breached: 'bg-destructive', met: 'bg-muted-foreground/40' }[status]
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{label}</span>
        <MetricPill status={status} />
      </div>
      {status !== 'met' && remaining !== null && (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={`${label}: time used`}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(used * 100)}>
          <div className={cn('h-full rounded-full transition-[width]', bar)} style={{ width: `${used * 100}%` }} />
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {done ? <>Done {formatRelative(done)} · target {minutesLabel(targetMinutes)}</>
          : remaining === null ? <>Target {minutesLabel(targetMinutes)}</>
          : remaining >= 0 ? <><span className={cn('font-medium', status === 'warning' ? 'text-warning' : 'text-foreground')}>{formatDuration(remaining)} left</span>{paused ? ' (paused)' : ''} · due {formatDateTime(due)}</>
          : <><span className="font-medium text-destructive">Overdue by {formatDuration(remaining)}</span> · was due {formatDateTime(due)}</>}
      </p>
    </div>
  )
}

function live(sla: TicketSLA, fetchedAt: number, now: number) {
  // Only a 24/7 clock can be advanced in the browser; working-hours clocks wait for the next server refresh.
  const elapsed = sla.business_hours_name ? 0 : Math.floor((now - fetchedAt) / 1000)
  return {
    response: sla.response_remaining_seconds === null ? null : sla.response_remaining_seconds - elapsed,
    resolution: sla.resolution_remaining_seconds === null ? null : sla.resolution_remaining_seconds - (sla.paused ? 0 : elapsed),
  }
}

export function TicketSLAPanel({ ticketId }: { ticketId: string }) {
  const q = useTicketSLA(ticketId)
  const now = useTick(!!q.data && !q.data.business_hours_name)
  if (q.isPending) return <Skeleton className="h-40" />
  if (q.isError) return null // the rest of the ticket stays usable; the list chip still shows status
  const sla = q.data
  if (!sla) {
    return (
      <Card>
        <CardHeader><CardTitle>SLA</CardTitle><CardDescription>No SLA policy applies to this ticket.</CardDescription></CardHeader>
      </Card>
    )
  }
  const remaining = live(sla, q.dataUpdatedAt, now)
  return (
    <Card>
      <CardHeader>
        <CardTitle>SLA</CardTitle>
        <CardDescription>{sla.policy_name} · {sla.business_hours_name ? `${sla.business_hours_name} (working time)` : '24/7'}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {sla.paused && sla.resolution_status !== 'met' && (
          <p className="flex items-center gap-1.5 rounded-md bg-muted px-2.5 py-1.5 text-xs">
            <Pause className="size-3.5" aria-hidden /> Resolution clock paused {sla.paused_at && formatRelative(sla.paused_at)} while waiting on the customer or parts.
          </p>
        )}
        <Metric label="First response" status={sla.response_status} due={sla.response_due_at} targetMinutes={sla.response_minutes}
          remaining={remaining.response} done={sla.responded_at} />
        <Metric label="Resolution" status={sla.resolution_status} due={sla.resolution_due_at} targetMinutes={sla.resolution_minutes}
          remaining={remaining.resolution} done={sla.resolved_at} paused={sla.paused} />
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Clock history ({sla.events.length})</summary>
          <ol className="mt-2 space-y-1">
            {sla.events.map((e) => (
              <li key={e.id} className="flex justify-between gap-2">
                <span>{EVENT_LABEL[e.type] ?? e.type}{e.metric && e.type !== 'applied' ? ` · ${e.metric === 'response' ? 'response' : 'resolution'}` : ''}</span>
                <time className="shrink-0 text-muted-foreground" dateTime={e.occurred_at} title={formatDateTime(e.occurred_at)}>{formatRelative(e.occurred_at)}</time>
              </li>
            ))}
          </ol>
        </details>
      </CardContent>
    </Card>
  )
}
