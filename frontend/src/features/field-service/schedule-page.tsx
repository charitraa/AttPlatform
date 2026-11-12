import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { type Appointment, type ScheduleData, useSchedule, WO_STATUS_LABEL, type WOStatus } from './api'
import { addDays, sameDay, startOfWeek } from './utils'

const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
const dayLabel = (d: Date) => d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' })

const CHIP: Record<string, string> = {
  confirmed: 'border-l-series-1 bg-series-1/10',
  completed: 'border-l-success bg-success/10',
  proposed: 'border-l-border bg-muted',
}

function Chip({ a }: { a: Appointment }) {
  return (
    <Link to={`/work-orders/${a.work_order.id}`}
      className={cn('block rounded-md border-l-[3px] px-2 py-1 text-xs hover:brightness-95 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none', CHIP[a.status] ?? CHIP.proposed)}
      title={`${a.work_order.reference} ${a.work_order.title} · ${a.work_order.customer}`}>
      <span className="font-medium tabular-nums">{time(a.starts_at)}–{time(a.ends_at)}</span>
      <span className="block truncate">{a.work_order.reference} · {a.work_order.customer}</span>
      <span className="block truncate text-muted-foreground">{WO_STATUS_LABEL[a.work_order.status as WOStatus] ?? a.work_order.status}</span>
    </Link>
  )
}

function Grid({ data, days }: { data: ScheduleData; days: Date[] }) {
  const today = new Date()
  const cell = useMemo(() => {
    const map = new Map<string, { appts: Appointment[]; off: ScheduleData['availability'] }>()
    const key = (t: string, d: Date) => `${t}|${d.toDateString()}`
    for (const t of data.technicians) for (const d of days) map.set(key(t.id, d), { appts: [], off: [] })
    for (const a of data.appointments) map.get(key(a.technician.id, new Date(a.starts_at)))?.appts.push(a)
    for (const b of data.availability.filter((x) => x.type === 'time_off')) {
      for (const d of days) {
        const dayStart = d.getTime()
        const dayEnd = addDays(d, 1).getTime()
        if (new Date(b.starts_at).getTime() < dayEnd && new Date(b.ends_at).getTime() > dayStart) map.get(key(b.technician_id, d))?.off.push(b)
      }
    }
    return (t: string, d: Date) => map.get(key(t, d))!
  }, [data, days])

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[56rem] table-fixed border-collapse text-sm">
        <caption className="sr-only">Technician schedule for the week</caption>
        <thead>
          <tr className="bg-muted/50">
            <th scope="col" className="w-40 border-b p-2 text-left font-medium">Technician</th>
            {days.map((d) => (
              <th key={d.toISOString()} scope="col" className={cn('border-b border-l p-2 text-left font-medium', sameDay(d, today) && 'text-primary')}>
                {dayLabel(d)}{sameDay(d, today) && <span className="sr-only"> (today)</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.technicians.map((t) => (
            <tr key={t.id} className="align-top">
              <th scope="row" className="border-b p-2 text-left font-normal">
                <Link to={`/technicians/${t.id}`} className="font-medium hover:underline">{t.name}</Link>
              </th>
              {days.map((d) => {
                const c = cell(t.id, d)
                return (
                  <td key={d.toISOString()} className={cn('h-24 border-b border-l p-1.5', sameDay(d, today) && 'bg-primary/[0.03]',
                    c.off.length > 0 && 'bg-[repeating-linear-gradient(45deg,transparent,transparent_6px,var(--muted)_6px,var(--muted)_8px)]')}>
                    {c.off.map((o) => <p key={o.id} className="mb-1 rounded bg-background/80 px-1.5 py-0.5 text-xs text-muted-foreground">Time off{o.note && `: ${o.note}`}</p>)}
                    <div className="space-y-1">{c.appts.sort((a, b) => a.starts_at.localeCompare(b.starts_at)).map((a) => <Chip key={a.id} a={a} />)}</div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function SchedulePage() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()))
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])
  const schedule = useSchedule(weekStart, addDays(weekStart, 7))
  const label = `${weekStart.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${addDays(weekStart, 6).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`
  const count = schedule.data?.appointments.filter((a) => a.status !== 'cancelled').length ?? 0

  return (
    <div className="space-y-5">
      <PageHeader
        title="Schedule"
        description={schedule.data ? `${count} visit${count === 1 ? '' : 's'} this week · ${label}` : label}
        actions={
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon-sm" aria-label="Previous week" onClick={() => setWeekStart(addDays(weekStart, -7))}><ChevronLeft /></Button>
            <Button variant="outline" size="sm" onClick={() => setWeekStart(startOfWeek(new Date()))}>This week</Button>
            <Button variant="outline" size="icon-sm" aria-label="Next week" onClick={() => setWeekStart(addDays(weekStart, 7))}><ChevronRight /></Button>
          </div>
        }
      />
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="h-3 w-1 rounded bg-series-1" aria-hidden /> Confirmed visit</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-1 rounded bg-success" aria-hidden /> Completed</span>
        <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-[repeating-linear-gradient(45deg,transparent,transparent_2px,var(--muted-foreground)_2px,var(--muted-foreground)_3px)] opacity-50" aria-hidden /> Time off</span>
        <span>Schedule a visit from the work order page.</span>
      </div>
      {schedule.isPending ? <Skeleton className="h-80" /> : schedule.isError ? <ErrorState error={schedule.error} onRetry={() => schedule.refetch()} /> :
        schedule.data.technicians.length === 0 ? <EmptyState title="No technicians yet" /> : <Grid data={schedule.data} days={days} />}
    </div>
  )
}
