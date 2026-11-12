import { CalendarClock, ChevronRight, MapPin, Navigation, Phone, Wrench } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { CheckboxField } from '@/components/forms/checkbox-field'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { PriorityLabel } from '@/features/tickets/components/badges'
import type { Priority } from '@/features/tickets/constants'
import { formatDateTime, formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { cn } from '@/lib/utils'
import { type Technician, type WorkOrderListItem, useMyTechnician, useTechMutation, useWorkOrder, useWorkOrders } from './api'
import { WOActions } from './components/wo-actions'
import { WOStatusBadge, WOStepper } from './components/wo-parts'
import { type ReporterState, useLocationReporter } from './use-location-reporter'
import { mapsUrl, sameDay } from './utils'

/** Statuses during which the technician is out in the field (and location may be recorded). */
const IN_FIELD = new Set(['en_route', 'on_site', 'in_progress'])
/** Order of attention: what's in progress first, then what's been accepted, then new assignments. */
const RANK: Record<string, number> = { in_progress: 0, on_site: 1, en_route: 2, accepted: 3, assigned: 4, created: 5 }

function byAttention(a: WorkOrderListItem, b: WorkOrderListItem) {
  const r = (RANK[a.status] ?? 9) - (RANK[b.status] ?? 9)
  if (r !== 0) return r
  const at = a.scheduled_start ? Date.parse(a.scheduled_start) : Infinity
  const bt = b.scheduled_start ? Date.parse(b.scheduled_start) : Infinity
  return at - bt
}

const LOCATION_NOTE: Record<ReporterState, string> = {
  off: '',
  waiting: 'Waiting for your position…',
  sharing: 'Sharing your position with dispatch while this job is active.',
  denied: 'Location permission was refused in this browser, so your position is not being shared.',
  unavailable: 'Your position is unavailable on this device right now.',
}

function Profile({ tech }: { tech: Technician }) {
  const { updateMe } = useTechMutation()
  const save = (body: { status?: string; location_sharing_enabled?: boolean }, ok: string) =>
    updateMe.mutate(body, { onSuccess: () => toast.success(ok), onError: (e) => toast.error(firstErrorMessage(e)) })
  const onDuty = tech.status === 'available' || tech.status === 'busy'
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className={cn('size-2.5 rounded-full', onDuty ? 'bg-success' : 'bg-muted-foreground')} aria-hidden />
          <div>
            <p className="text-sm font-medium">{onDuty ? (tech.status === 'busy' ? 'On a job' : 'On duty') : tech.status === 'on_leave' ? 'On leave' : 'Off duty'}</p>
            <p className="text-xs text-muted-foreground">{tech.jobs_today} today · {tech.active_jobs} open</p>
          </div>
        </div>
        <div className="flex flex-col gap-3 sm:items-end">
          {tech.status !== 'on_leave' && (
            <button type="button" disabled={updateMe.isPending}
              className="self-start rounded-md border px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50 sm:self-auto"
              onClick={() => save({ status: onDuty ? 'off_duty' : 'available' }, onDuty ? 'You are off duty' : 'You are on duty')}>
              {onDuty ? 'Go off duty' : 'Go on duty'}
            </button>
          )}
          <CheckboxField label="Share my location during jobs" checked={tech.location_sharing_enabled} disabled={updateMe.isPending}
            description="Only while travelling to or working on a job. Never off duty."
            onChange={(e) => save({ location_sharing_enabled: e.target.checked }, e.target.checked ? 'Location sharing on' : 'Location sharing off')} />
        </div>
      </CardContent>
    </Card>
  )
}

function CurrentJob({ id, shareLocation }: { id: string; shareLocation: boolean }) {
  const query = useWorkOrder(id)
  const reporter = useLocationReporter(shareLocation && !!query.data && IN_FIELD.has(query.data.status))
  if (query.isPending) return <Skeleton className="h-64" />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  const wo = query.data
  const map = mapsUrl(wo)
  return (
    <Card className="border-primary/40">
      <CardHeader className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-muted-foreground">{wo.reference}</span>
          <WOStatusBadge status={wo.status} />
          <PriorityLabel priority={wo.priority as Priority} />
        </div>
        <CardTitle className="text-lg break-words">{wo.title}</CardTitle>
        <p className="text-sm text-muted-foreground">{wo.customer.name}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <WOStepper status={wo.status} />
        {wo.appointment && (
          <p className="flex items-center gap-1.5 text-sm"><CalendarClock className="size-4 text-muted-foreground" aria-hidden />
            {formatDateTime(wo.appointment.starts_at)} – {formatDateTime(wo.appointment.ends_at)}</p>
        )}
        {wo.service_address && (
          <p className="flex items-start gap-1.5 text-sm"><MapPin className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />{wo.service_address}</p>
        )}
        {wo.description && <p className="line-clamp-4 text-sm whitespace-pre-wrap">{wo.description}</p>}
        <div className="grid grid-cols-2 gap-2">
          {map && (
            <a href={map} target="_blank" rel="noreferrer noopener" className="inline-flex h-11 items-center justify-center gap-2 rounded-md border text-sm font-medium hover:bg-muted">
              <Navigation className="size-4" aria-hidden /> Directions
            </a>
          )}
          <Link to={`/work-orders/${wo.id}`} className="inline-flex h-11 items-center justify-center gap-2 rounded-md border text-sm font-medium hover:bg-muted">
            Full details <ChevronRight className="size-4" aria-hidden />
          </Link>
        </div>
        <WOActions wo={wo} size="lg" shareLocation={shareLocation} className="[&>button]:min-h-11 [&>button]:grow" />
        {reporter !== 'off' && (
          <p role="status" className={cn('text-xs', reporter === 'denied' || reporter === 'unavailable' ? 'text-warning' : 'text-muted-foreground')}>
            {LOCATION_NOTE[reporter]}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function JobRow({ wo, now }: { wo: WorkOrderListItem; now: Date }) {
  const today = wo.scheduled_start && sameDay(new Date(wo.scheduled_start), now)
  return (
    <li>
      <Link to={`/work-orders/${wo.id}`} className="flex items-center gap-3 rounded-lg border bg-card p-3 transition-colors hover:bg-muted/40">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{wo.reference}</span>
            <WOStatusBadge status={wo.status} />
          </div>
          <p className="truncate text-sm font-medium">{wo.title}</p>
          <p className="truncate text-xs text-muted-foreground">
            {wo.customer.name}
            {wo.scheduled_start ? ` · ${today ? 'today ' : ''}${formatDateTime(wo.scheduled_start)}` : ' · not scheduled'}
          </p>
        </div>
        <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </Link>
    </li>
  )
}

export function MyJobsPage() {
  const [now] = useState(() => new Date())
  const me = useMyTechnician()
  const jobs = useWorkOrders({ technician: 'me', status: 'active', ordering: 'scheduled_start' })
  const done = useWorkOrders({ technician: 'me', status: 'completed', ordering: '-updated_at' })

  if (me.isPending || jobs.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-40" /><Skeleton className="h-20" /><Skeleton className="h-64" /></div>
  if (me.isError) return <ErrorState error={me.error} onRetry={() => me.refetch()} />
  if (jobs.isError) return <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />

  const open = [...jobs.data.results].sort(byAttention)
  const [current, ...rest] = open
  const recent = (done.data?.results ?? []).slice(0, 5)

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <PageHeader title="My jobs" description="Your assigned work, most urgent first." />
      <Profile tech={me.data} />

      {current ? <CurrentJob key={current.id} id={current.id} shareLocation={me.data.location_sharing_enabled} /> : (
        <EmptyState icon={Wrench} title="No open jobs" description="New assignments appear here as soon as dispatch sends them." />
      )}

      {rest.length > 0 && (
        <section aria-labelledby="up-next" className="space-y-2">
          <h2 id="up-next" className="text-sm font-semibold">Up next <span className="font-normal text-muted-foreground">({rest.length})</span></h2>
          <ul className="space-y-2">{rest.map((wo) => <JobRow key={wo.id} wo={wo} now={now} />)}</ul>
        </section>
      )}

      {recent.length > 0 && (
        <section aria-labelledby="recent" className="space-y-2">
          <h2 id="recent" className="text-sm font-semibold">Recently completed</h2>
          <ul className="space-y-2">
            {recent.map((wo) => (
              <li key={wo.id} className="flex items-center justify-between gap-3 text-sm">
                <Link to={`/work-orders/${wo.id}`} className="min-w-0 truncate hover:underline">{wo.reference} · {wo.title}</Link>
                <span className={cn('shrink-0 text-xs', wo.customer_confirmed_at ? 'text-muted-foreground' : 'text-warning')}>
                  {wo.customer_confirmed_at ? `signed off ${formatRelative(wo.customer_confirmed_at)}` : 'awaiting sign-off'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Phone className="size-3.5" aria-hidden /> Problem on site? Contact dispatch before handing a job back.</p>
    </div>
  )
}
