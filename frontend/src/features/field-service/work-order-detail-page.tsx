import { ArrowLeft, MapPin, Star } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ErrorState } from '@/components/common/states'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { PriorityLabel } from '@/features/tickets/components/badges'
import type { Priority } from '@/features/tickets/constants'
import { ApiError } from '@/lib/api/client'
import { formatDateTime, formatRelative } from '@/lib/format'
import { useStatusLog, useWorkOrder, WO_STATUS_LABEL, type WOStatus } from './api'
import { WOActions } from './components/wo-actions'
import { EvidenceGallery, WOStatusBadge, WOStepper } from './components/wo-parts'
import { mapsUrl } from './utils'

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

const money = (amount: string | null, currency: string) => (amount ? `${currency} ${Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '—')

function StatusLog({ id }: { id: string }) {
  const log = useStatusLog(id)
  return (
    <ol className="relative space-y-3 border-l pl-4">
      {[...(log.data ?? [])].reverse().map((e) => (
        <li key={e.id} className="relative text-sm">
          <span className="absolute top-1.5 -left-[21px] size-2 rounded-full bg-border ring-4 ring-card" aria-hidden />
          <span className="font-medium">{e.actor?.full_name ?? 'System'}</span>{' '}
          <span className="text-muted-foreground">
            {e.from_status === e.to_status ? e.note : `${e.from_status ? `${WO_STATUS_LABEL[e.from_status as WOStatus]} → ` : ''}${WO_STATUS_LABEL[e.to_status as WOStatus]}`}
          </span>
          {e.note && e.from_status !== e.to_status && <span className="block text-xs text-muted-foreground">{e.note}</span>}
          <time className="block text-xs text-muted-foreground" dateTime={e.created_at} title={formatDateTime(e.created_at)}>{formatRelative(e.created_at)}</time>
        </li>
      ))}
    </ol>
  )
}

export function WorkOrderDetailPage() {
  const { id = '' } = useParams()
  const query = useWorkOrder(id)
  if (query.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-48" /></div>
  if (query.isError) {
    const missing = query.error instanceof ApiError && query.error.status === 404
    return <ErrorState error={missing ? new Error("This work order doesn't exist or isn't assigned to you.") : query.error} onRetry={missing ? undefined : () => query.refetch()} />
  }
  const wo = query.data
  const map = mapsUrl(wo)

  return (
    <div className="space-y-6">
      <div className="space-y-3 border-b pb-5">
        <Link to="/work-orders" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Work orders</Link>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm text-muted-foreground">{wo.reference}</span>
              <WOStatusBadge status={wo.status} />
              <PriorityLabel priority={wo.priority as Priority} />
              {wo.ticket && <Link to={`/tickets/${wo.ticket.id}`} className="text-sm text-muted-foreground hover:underline">from {wo.ticket.reference}</Link>}
            </div>
            <h1 className="text-xl font-semibold tracking-tight break-words">{wo.title}</h1>
          </div>
          <WOActions wo={wo} />
        </div>
        <WOStepper status={wo.status} />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader><CardTitle>Job</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {wo.description ? <p className="text-sm whitespace-pre-wrap">{wo.description}</p> : <p className="text-sm text-muted-foreground">No description.</p>}
              {wo.service_address && (
                <p className="flex items-start gap-1.5 text-sm"><MapPin className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span>{wo.service_address}{map && <> · <a href={map} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">Open map</a></>}</span>
                </p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Photos and documents</CardTitle></CardHeader>
            <CardContent>
              <EvidenceGallery workOrderId={wo.id} canUpload={wo.capabilities.add_evidence}
                defaultKind={['created', 'assigned', 'accepted', 'en_route', 'on_site'].includes(wo.status) ? 'before_photo' : 'after_photo'} />
            </CardContent>
          </Card>
          {(wo.status === 'completed' || wo.completion_summary) && (
            <Card className="border-success/40">
              <CardHeader><CardTitle>Completion report</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm whitespace-pre-wrap">{wo.completion_summary}</p>
                {wo.parts_used.length > 0 && (
                  <ul className="text-sm">{wo.parts_used.map((p, i) => <li key={i}>{p.quantity} × {p.name}{p.unit_cost && ` @ ${money(p.unit_cost, wo.currency)}`}</li>)}</ul>
                )}
                <dl className="grid grid-cols-3 gap-3 border-t pt-3 text-sm">
                  <div><dt className="text-xs text-muted-foreground">Time on site</dt><dd>{wo.labor_minutes ? `${Math.floor(wo.labor_minutes / 60)}h ${wo.labor_minutes % 60}m` : '—'}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Labour</dt><dd>{money(wo.labor_cost, wo.currency)}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Parts</dt><dd>{money(wo.parts_cost, wo.currency)}</dd></div>
                </dl>
                {wo.customer_confirmed_at ? (
                  <div className="rounded-md bg-muted p-3 text-sm">
                    Confirmed by <span className="font-medium">{wo.customer_signed_by}</span> {formatRelative(wo.customer_confirmed_at)}
                    {wo.customer_rating && <span className="ml-2 inline-flex items-center gap-0.5" aria-label={`${wo.customer_rating} out of 5`}>{Array.from({ length: wo.customer_rating }, (_, i) => <Star key={i} className="size-3.5 fill-warning text-warning" aria-hidden />)}</span>}
                    {wo.customer_comment && <p className="mt-1 text-muted-foreground">"{wo.customer_comment}"</p>}
                  </div>
                ) : <p className="text-sm text-warning">Awaiting customer confirmation.</p>}
              </CardContent>
            </Card>
          )}
          {wo.cancelled_reason && <Card><CardHeader><CardTitle>Cancelled</CardTitle></CardHeader><CardContent><p className="text-sm">{wo.cancelled_reason}</p></CardContent></Card>}
        </div>
        <aside className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Details</CardTitle></CardHeader>
            <CardContent>
              <dl className="divide-y">
                <Row label="Customer"><Link to={`/customers/${wo.customer.id}`} className="hover:underline">{wo.customer.name}</Link></Row>
                <Row label="Asset">{wo.asset ? <>{wo.asset.asset_tag} · {wo.asset.name}{wo.asset.serial_number && <span className="block font-mono text-xs text-muted-foreground">{wo.asset.serial_number}</span>}</> : '—'}</Row>
                <Row label="Technician">{wo.technician ? <Link to={`/technicians/${wo.technician.id}`} className="hover:underline">{wo.technician.name}</Link> : <span className="text-muted-foreground">Unassigned</span>}</Row>
                <Row label="Visit">{wo.appointment ? <>{formatDateTime(wo.appointment.starts_at)}<span className="block text-xs text-muted-foreground">until {formatDateTime(wo.appointment.ends_at)}</span>{wo.appointment.notes && <span className="block text-xs">{wo.appointment.notes}</span>}</> : <span className="text-muted-foreground">Not scheduled</span>}</Row>
                {wo.actual_start && <Row label="Started">{formatDateTime(wo.actual_start)}</Row>}
                {wo.actual_end && <Row label="Finished">{formatDateTime(wo.actual_end)}</Row>}
                <Row label="Created">{formatDateTime(wo.created_at)}{wo.created_by && <span className="block text-xs text-muted-foreground">by {wo.created_by.full_name}</span>}</Row>
              </dl>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Status history</CardTitle></CardHeader>
            <CardContent><StatusLog id={wo.id} /></CardContent>
          </Card>
        </aside>
      </div>
    </div>
  )
}
