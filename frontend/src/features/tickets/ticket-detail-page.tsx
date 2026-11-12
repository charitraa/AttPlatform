import { ArrowLeft, Archive, Clock } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ErrorState } from '@/components/common/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api/client'
import { formatDateTime, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useCan } from '@/stores/auth'
import { AIPanel } from '@/features/ai/components/ai-panel'
import { useTicket } from './api'
import { AttachmentsPanel } from './components/attachments-panel'
import { PriorityLabel, StatusBadge } from './components/badges'
import { Conversation } from './components/conversation'
import { TicketActions } from './components/ticket-actions'
import { Timeline } from './components/timeline'
import { CHANNEL_LABEL } from './constants'

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

const muted = (text: string) => <span className="text-muted-foreground">{text}</span>

export function TicketDetailPage() {
  const { id = '' } = useParams()
  const ticket = useTicket(id)
  const canSeeCustomers = useCan('customers.view')

  if (ticket.isPending) {
    return <div className="space-y-4"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-48" /><Skeleton className="h-32" /></div>
  }
  if (ticket.isError) {
    const notFound = ticket.error instanceof ApiError && ticket.error.status === 404
    return notFound ? (
      <ErrorState error={new Error("This ticket doesn't exist or you don't have access to it.")} />
    ) : <ErrorState error={ticket.error} onRetry={() => ticket.refetch()} />
  }

  const t = ticket.data
  return (
    <div className="space-y-6">
      <div className="space-y-3 border-b pb-5">
        <Link to="/tickets" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Tickets
        </Link>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm text-muted-foreground">{t.reference}</span>
              <StatusBadge status={t.status} />
              <PriorityLabel priority={t.priority} />
              {t.priority_source !== 'manual' && (
                <span className="text-xs text-muted-foreground">({t.priority_source === 'ai' ? 'set by AI' : 'category default'})</span>
              )}
              {t.archived_at && <Badge variant="outline" className="gap-1"><Archive className="size-3" /> Archived</Badge>}
              {t.is_overdue && <Badge variant="outline" className="gap-1 border-destructive/50 text-destructive"><Clock className="size-3" /> Overdue</Badge>}
            </div>
            <h1 className="text-xl font-semibold tracking-tight break-words">{t.title}</h1>
          </div>
          <TicketActions ticket={t} />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader><CardTitle>Description</CardTitle></CardHeader>
            <CardContent><p className="text-sm break-words whitespace-pre-wrap">{t.description}</p></CardContent>
          </Card>
          {t.resolution_notes && (
            <Card className="border-success/40">
              <CardHeader><CardTitle>Resolution</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                <p className="text-sm whitespace-pre-wrap">{t.resolution_notes}</p>
                {t.customer_confirmed_at && <p className="text-xs text-muted-foreground">Confirmed by the customer {formatRelative(t.customer_confirmed_at)}</p>}
              </CardContent>
            </Card>
          )}
          <Conversation ticket={t} />
        </div>

        <aside className="space-y-6">
          <AIPanel ticketId={t.id} closed={t.status === 'closed' || !!t.archived_at} />
          <Card>
            <CardHeader><CardTitle>Details</CardTitle></CardHeader>
            <CardContent>
              <dl className="divide-y">
                <Row label="Customer">
                  {canSeeCustomers ? <Link className="hover:underline" to={`/customers/${t.customer.id}`}>{t.customer.name}</Link> : t.customer.name}
                </Row>
                <Row label="Contact">{t.contact ? <>{t.contact.name}{t.contact.email && <span className="block text-xs text-muted-foreground">{t.contact.email}</span>}</> : muted('—')}</Row>
                <Row label="Asset">
                  {t.asset ? <>{t.asset.asset_tag} · {t.asset.name}<span className={cn('block text-xs', t.asset.under_warranty ? 'text-success' : 'text-muted-foreground')}>{t.asset.under_warranty ? 'Under warranty' : 'Out of warranty'}</span></> : muted('—')}
                </Row>
                <Row label="Category">{t.category?.name ?? muted('Uncategorised')}</Row>
                <Row label="Agent">{t.assigned_agent?.full_name ?? muted('Unassigned')}</Row>
                <Row label="Technician">{t.assigned_technician?.full_name ?? muted('None')}</Row>
                <Row label="Channel">{CHANNEL_LABEL[t.channel as keyof typeof CHANNEL_LABEL] ?? t.channel}</Row>
                {t.tags.length > 0 && <Row label="Tags"><div className="flex flex-wrap gap-1">{t.tags.map((tag) => <Badge key={tag} variant="secondary">{tag}</Badge>)}</div></Row>}
              </dl>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Dates</CardTitle></CardHeader>
            <CardContent>
              <dl className="divide-y">
                <Row label="Created">{formatDateTime(t.created_at)}{t.created_by && <span className="block text-xs text-muted-foreground">by {t.created_by.full_name}</span>}</Row>
                <Row label="Due">{t.due_at ? <span className={cn(t.is_overdue && 'font-medium text-destructive')}>{formatDateTime(t.due_at)}</span> : muted('No deadline yet')}</Row>
                <Row label="First response">{t.first_response_at ? formatDateTime(t.first_response_at) : muted('Awaiting reply')}</Row>
                {t.resolved_at && <Row label="Resolved">{formatDateTime(t.resolved_at)}</Row>}
                {t.closed_at && <Row label="Closed">{formatDateTime(t.closed_at)}</Row>}
              </dl>
            </CardContent>
          </Card>
          <AttachmentsPanel ticket={t} />
          <Timeline ticketId={t.id} />
        </aside>
      </div>
      {!t.capabilities.edit && t.archived_at && (
        <Button variant="outline" nativeButton={false} render={<Link to="/tickets?archived=true" />}>View archived tickets</Button>
      )}
    </div>
  )
}
