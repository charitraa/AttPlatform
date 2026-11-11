import { AlertTriangle, Clock, Inbox, Table2, TrendingUp, UserX } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useTickets } from '@/features/tickets/api'
import { PriorityLabel, StatusBadge } from '@/features/tickets/components/badges'
import { describeEvent } from '@/features/tickets/describe-event'
import { formatHours, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAuthStore, useCan } from '@/stores/auth'
import { type Summary, useActivity, useBreakdown, useSummary, useTrends, useWorkload } from './api'

// ------------------------------------------------------------------- stat tiles
function StatTile({ label, value, hint, to, icon: Icon, tone }: {
  label: string; value: ReactNode; hint?: string; to?: string; icon?: typeof Inbox; tone?: 'danger'
}) {
  const body = (
    <div className={cn('flex h-full flex-col gap-1 rounded-xl border bg-card p-4 transition-colors', to && 'hover:bg-muted/50')}>
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">{Icon && <Icon className="size-3.5" aria-hidden />}{label}</span>
      <span className={cn('text-2xl font-semibold tabular-nums tracking-tight', tone === 'danger' && 'text-destructive')}>{value}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  )
  return to ? <Link to={to} className="block rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none">{body}</Link> : body
}

function UnavailableTile({ label, reason }: { label: string; reason: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-dashed p-4">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold text-muted-foreground/60" aria-label="Not available">—</span>
      <span className="text-xs text-muted-foreground">{reason}</span>
    </div>
  )
}

function Tiles({ s }: { s: Summary }) {
  const danger = (n: number) => (n > 0 ? 'danger' as const : undefined)
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
      <StatTile label="Open tickets" value={s.open} icon={Inbox} to="/tickets" hint={`${s.total} total`} />
      <StatTile label="In progress" value={s.in_progress} to="/tickets?status=in_progress" hint={`${s.new} new`} />
      <StatTile label="Critical open" value={s.critical_open} icon={AlertTriangle} tone={danger(s.critical_open)} to="/tickets?priority=critical" />
      <StatTile label="Overdue" value={s.overdue} icon={Clock} tone={danger(s.overdue)} to="/tickets?overdue=true" />
      <StatTile label="Unassigned" value={s.unassigned_open} icon={UserX} to="/tickets?assigned_agent=none" />
      <StatTile label="Resolved" value={s.resolved} to="/tickets?status=resolved" hint={`${s.closed} closed`} />
      <StatTile label="Avg resolution" value={formatHours(s.avg_resolution_hours)} hint={`last ${s.period_days} days`} />
      <StatTile label="Avg first response" value={formatHours(s.avg_first_response_hours)} hint={`last ${s.period_days} days`} />
      <StatTile label="Created / resolved" value={`${s.created_in_period} / ${s.resolved_in_period}`} icon={TrendingUp} hint={`last ${s.period_days} days`} />
      <UnavailableTile label="SLA compliance" reason={s.unavailable.sla_compliance ?? 'Not available yet.'} />
      <UnavailableTile label="Technicians available" reason={s.unavailable.technicians_available ?? 'Not available yet.'} />
      <UnavailableTile label="Active work orders" reason={s.unavailable.active_work_orders ?? 'Not available yet.'} />
    </div>
  )
}

// ------------------------------------------------------------------- trend chart
const dayLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

function TrendTooltip({ active, payload, label }: { active?: boolean; payload?: { dataKey: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length || !label) return null
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <div className="mb-1 font-medium">{dayLabel(label)}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="inline-block h-0.5 w-3 rounded" style={{ background: p.color }} aria-hidden />
          <span className="text-muted-foreground">{p.dataKey === 'created' ? 'Created' : 'Resolved'}</span>
          <span className="ml-auto font-medium tabular-nums">{p.value}</span>
        </div>
      ))}
    </div>
  )
}

function TrendCard({ days }: { days: number }) {
  const trends = useTrends(days)
  const [asTable, setAsTable] = useState(false)
  const data = trends.data?.days ?? []
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="space-y-1">
          <CardTitle>Tickets created vs resolved</CardTitle>
          <CardDescription>Per day, last {days} days</CardDescription>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          <Table2 /> {asTable ? 'Show chart' : 'View as table'}
        </Button>
      </CardHeader>
      <CardContent>
        {trends.isPending ? <Skeleton className="h-64" /> : trends.isError ? <ErrorState error={trends.error} onRetry={() => trends.refetch()} /> : asTable ? (
          <div className="max-h-64 overflow-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Day</TableHead><TableHead className="text-right">Created</TableHead><TableHead className="text-right">Resolved</TableHead></TableRow></TableHeader>
              <TableBody>{[...data].reverse().map((d) => (
                <TableRow key={d.date}><TableCell>{dayLabel(d.date)}</TableCell><TableCell className="text-right tabular-nums">{d.created}</TableCell><TableCell className="text-right tabular-nums">{d.resolved}</TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </div>
        ) : (
          <div className="h-64" role="img" aria-label={`Line chart of tickets created and resolved per day over the last ${days} days. Use "View as table" for the values.`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis dataKey="date" tickFormatter={dayLabel} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} width={36} />
                <Tooltip content={<TrendTooltip />} cursor={{ stroke: 'var(--muted-foreground)', strokeDasharray: '3 3' }} />
                <Legend verticalAlign="top" align="right" height={28} iconType="plainline"
                  formatter={(v: string) => <span className="text-xs text-muted-foreground">{v === 'created' ? 'Created' : 'Resolved'}</span>} />
                <Line type="monotone" dataKey="created" stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} />
                <Line type="monotone" dataKey="resolved" stroke="var(--series-2)" strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------- bar lists
/** Single-series horizontal bars: value printed as text, so colour carries no meaning on its own. */
function BarList({ rows, emptyText }: { rows: { key: string; label: ReactNode; value: number; to?: string }[]; emptyText: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  if (rows.every((r) => r.value === 0)) return <p className="text-sm text-muted-foreground">{emptyText}</p>
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => {
        const content = (
          <>
            <div className="mb-1 flex items-center justify-between gap-2 text-sm"><span className="truncate">{r.label}</span><span className="font-medium tabular-nums">{r.value}</span></div>
            <div className="h-2 rounded-full bg-muted" aria-hidden>
              <div className="h-2 rounded-full bg-series-1" style={{ width: `${(r.value / max) * 100}%`, minWidth: r.value ? 4 : 0 }} />
            </div>
          </>
        )
        return <li key={r.key}>{r.to ? <Link to={r.to} className="block rounded hover:bg-muted/40">{content}</Link> : content}</li>
      })}
    </ul>
  )
}

function BreakdownCards() {
  const breakdown = useBreakdown()
  if (breakdown.isPending) return <><Skeleton className="h-56" /><Skeleton className="h-56" /></>
  if (breakdown.isError) return <ErrorState error={breakdown.error} onRetry={() => breakdown.refetch()} />
  const b = breakdown.data
  return (
    <>
      <Card>
        <CardHeader><CardTitle>Open tickets by priority</CardTitle></CardHeader>
        <CardContent>
          <BarList emptyText="No open tickets."
            rows={[...b.priority].reverse().map((p) => ({ key: p.priority, label: <PriorityLabel priority={p.priority} />, value: p.count, to: `/tickets?priority=${p.priority}` }))} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Tickets by status</CardTitle></CardHeader>
        <CardContent>
          <BarList emptyText="No tickets yet."
            rows={b.status.filter((s) => s.count > 0).map((s) => ({ key: s.status, label: s.label, value: s.count, to: `/tickets?status=${s.status}` }))} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Open tickets by category</CardTitle></CardHeader>
        <CardContent>
          <BarList emptyText="No open tickets." rows={b.category.map((c) => ({ key: c.category, label: c.category, value: c.count }))} />
        </CardContent>
      </Card>
    </>
  )
}

// --------------------------------------------------------------- lists
function RecentTickets() {
  const tickets = useTickets({ ordering: '-created_at', status: 'active' })
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between"><CardTitle>Recent open tickets</CardTitle>
        <Link to="/tickets" className="text-sm text-muted-foreground hover:text-foreground">View all</Link></CardHeader>
      <CardContent>
        {tickets.isPending ? <Skeleton className="h-40" /> : !tickets.data?.results.length ? <EmptyState title="No open tickets" className="py-6" /> : (
          <ul className="divide-y">
            {tickets.data.results.slice(0, 6).map((t) => (
              <li key={t.id} className="flex items-center gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <Link to={`/tickets/${t.id}`} className="block truncate text-sm font-medium hover:underline">{t.title}</Link>
                  <span className="text-xs text-muted-foreground">{t.reference} · {t.customer.name} · {formatRelative(t.created_at)}</span>
                </div>
                <PriorityLabel priority={t.priority} className="hidden sm:inline-flex" />
                <StatusBadge status={t.status} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function ActivityFeed() {
  const activity = useActivity()
  return (
    <Card>
      <CardHeader><CardTitle>Recent activity</CardTitle></CardHeader>
      <CardContent>
        {activity.isPending ? <Skeleton className="h-40" /> : !activity.data?.events.length ? <p className="text-sm text-muted-foreground">Nothing yet.</p> : (
          <ul className="space-y-3">
            {activity.data.events.slice(0, 6).map((e) => (
              <li key={e.id} className="text-sm">
                <span className="font-medium">{e.actor}</span> <span className="text-muted-foreground">{describeEvent(e)}</span>{' '}
                <Link to={`/tickets/${e.ticket.id}`} className="font-mono text-xs hover:underline">{e.ticket.reference}</Link>
                <span className="block text-xs text-muted-foreground">{formatRelative(e.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function Workload({ days }: { days: number }) {
  const workload = useWorkload(days, true)
  return (
    <Card>
      <CardHeader><CardTitle>Agent workload</CardTitle><CardDescription>Open now · resolved and average resolution over the last {days} days</CardDescription></CardHeader>
      <CardContent className="p-0">
        {workload.isPending ? <div className="p-4"><Skeleton className="h-32" /></div> : !workload.data?.agents.length ? <p className="px-6 pb-4 text-sm text-muted-foreground">No assigned tickets yet.</p> : (
          <Table>
            <TableHeader><TableRow><TableHead>Agent</TableHead><TableHead className="text-right">Open</TableHead><TableHead className="text-right">Resolved</TableHead><TableHead className="text-right">Avg resolution</TableHead></TableRow></TableHeader>
            <TableBody>{workload.data.agents.map((a) => (
              <TableRow key={a.user_id}><TableCell>{a.name}</TableCell><TableCell className="text-right tabular-nums">{a.open}</TableCell><TableCell className="text-right tabular-nums">{a.resolved}</TableCell><TableCell className="text-right tabular-nums">{formatHours(a.avg_resolution_hours)}</TableCell></TableRow>
            ))}</TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

export function DashboardPage() {
  const [days, setDays] = useState(30)
  const summary = useSummary(days)
  const seesAll = useCan('tickets.view_all')
  const firstName = useAuthStore((s) => s.user?.first_name)

  return (
    <div className="space-y-6">
      <PageHeader
        title={firstName ? `Welcome back, ${firstName}` : 'Dashboard'}
        description={seesAll ? 'Service desk overview for your organization.' : 'An overview of your tickets.'}
        actions={
          <NativeSelect aria-label="Period" className="w-40" value={String(days)} onChange={(e) => setDays(Number(e.target.value))}>
            <option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option>
          </NativeSelect>
        }
      />
      {summary.isPending ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">{Array.from({ length: 12 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div>
      ) : summary.isError ? <ErrorState error={summary.error} onRetry={() => summary.refetch()} /> : <Tiles s={summary.data} />}

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2"><TrendCard days={days} /></div>
        <ActivityFeed />
      </div>
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3"><BreakdownCards /></div>
      <div className="grid gap-6 xl:grid-cols-2">
        <RecentTickets />
        {seesAll && <Workload days={days} />}
      </div>
    </div>
  )
}
