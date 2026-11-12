import { BarChart3, Download } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Field } from '@/components/forms/field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDate } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { cn } from '@/lib/utils'
import { REPORTS, type ReportColumn, type ReportName, downloadReport, useReport } from './api'

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const before = (today: string, n: number) => { const d = new Date(`${today}T00:00:00`); d.setDate(d.getDate() - n); return iso(d) }
const PRESETS = [{ label: '7 days', days: 6 }, { label: '30 days', days: 29 }, { label: '90 days', days: 89 }, { label: '12 months', days: 364 }]

function cell(value: string | number | null | undefined, col: ReportColumn) {
  if (value === null || value === undefined || value === '') return <span className="text-muted-foreground">—</span>
  if (col.kind === 'percent' && typeof value === 'number') return `${Math.round(value * 100)}%`
  if (col.kind === 'hours' && typeof value === 'number') return value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  if (col.kind === 'date' && typeof value === 'string') return formatDate(value)
  return typeof value === 'number' ? value.toLocaleString() : value
}

export function AnalyticsPage() {
  const [today] = useState(() => iso(new Date()))
  const [params, setParams] = useSearchParams()
  const name = (REPORTS.find((r) => r.name === params.get('report'))?.name ?? 'ticket_volume') as ReportName
  const end = params.get('end') ?? today
  const start = params.get('start') ?? before(today, 29)
  const set = (patch: Record<string, string>) => setParams((p) => { for (const [k, v] of Object.entries(patch)) p.set(k, v); return p }, { replace: true })
  const report = useReport(name, start, end)
  const [downloading, setDownloading] = useState(false)

  const download = async () => {
    setDownloading(true)
    try { await downloadReport(name, start, end) } catch (e) { toast.error(firstErrorMessage(e)) } finally { setDownloading(false) }
  }
  const totals = report.data && name === 'ticket_volume'
    ? { created: report.data.rows.reduce((a, r) => a + Number(r.created ?? 0), 0), resolved: report.data.rows.reduce((a, r) => a + Number(r.resolved ?? 0), 0) }
    : null

  return (
    <div className="space-y-5">
      <PageHeader title="Analytics" description="Reports over any period up to a year, in your organization's time zone. Export any of them as CSV."
        actions={<Button variant="outline" onClick={download} disabled={downloading || !report.data}><Download /> {downloading ? 'Preparing…' : 'Export CSV'}</Button>} />

      <div role="tablist" aria-label="Report" className="flex flex-wrap gap-1 border-b">
        {REPORTS.map((r) => (
          <button key={r.name} role="tab" type="button" aria-selected={r.name === name}
            className={cn('-mb-px border-b-2 px-3 py-2 text-sm transition-colors', r.name === name ? 'border-primary font-medium text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground')}
            onClick={() => set({ report: r.name })}>{r.label}</button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label="From"><Input type="date" className="w-40" value={start} max={end} onChange={(e) => e.target.value && set({ start: e.target.value })} /></Field>
        <Field label="To"><Input type="date" className="w-40" value={end} min={start} max={today} onChange={(e) => e.target.value && set({ end: e.target.value })} /></Field>
        <div className="flex gap-1 pb-0.5" role="group" aria-label="Quick ranges">
          {PRESETS.map((p) => (
            <Button key={p.label} size="sm" variant={start === before(today, p.days) && end === today ? 'secondary' : 'ghost'}
              onClick={() => set({ start: before(today, p.days), end: today })}>{p.label}</Button>
          ))}
        </div>
      </div>

      {report.isPending ? <Skeleton className="h-72" /> : report.isError ? <ErrorState error={report.error} onRetry={() => report.refetch()} /> : (
        <section aria-labelledby="report-title" className={cn('space-y-3 transition-opacity', report.isFetching && 'opacity-60')}>
          <div>
            <h2 id="report-title" className="font-semibold">{report.data.title}</h2>
            <p className="text-sm text-muted-foreground">{report.data.description} {formatDate(report.data.start)} – {formatDate(report.data.end)}.</p>
          </div>
          {totals && <p className="text-sm"><span className="font-medium tabular-nums">{totals.created}</span> created · <span className="font-medium tabular-nums">{totals.resolved}</span> resolved in this period</p>}
          {report.data.rows.length === 0 ? <EmptyState icon={BarChart3} title="No data for this period" description="Try a longer range." /> : (
            <div className="overflow-x-auto rounded-xl border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>{report.data.columns.map((c) => <TableHead key={c.key} className={cn(c.kind !== 'text' && c.kind !== 'date' && 'text-right')}>{c.label}</TableHead>)}</TableRow>
                </TableHeader>
                <TableBody>
                  {report.data.rows.map((row, i) => (
                    <TableRow key={i}>
                      {report.data.columns.map((c) => (
                        <TableCell key={c.key} className={cn(c.kind !== 'text' && c.kind !== 'date' && 'text-right tabular-nums', c.kind === 'text' && 'max-w-[16rem] truncate')}>{cell(row[c.key], c)}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
