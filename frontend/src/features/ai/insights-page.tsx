import { AlertTriangle, BrainCircuit, Clock, Loader2, Repeat, Sparkles, TrendingUp, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useQueryClient } from '@tanstack/react-query'
import { formatDate, formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { type Insight, useAIStatus, useDismissInsight, useGenerateInsights, useInsights, waitForAnalysis } from './api'
import { DemoBadge } from './components/ai-panel'
import { TYPE_LABEL } from './format'

const INSIGHT_META: Record<Insight['type'], { label: string; icon: typeof Repeat }> = {
  recurring_issue: { label: 'Recurring issue', icon: Repeat },
  pattern: { label: 'Pattern', icon: TrendingUp },
  sla_risk: { label: 'Deadline risk', icon: Clock },
  report: { label: 'Report', icon: BrainCircuit },
}

function InsightCard({ insight }: { insight: Insight }) {
  const dismiss = useDismissInsight()
  const meta = INSIGHT_META[insight.type]
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="space-y-1">
          <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><meta.icon className="size-3.5" aria-hidden /> {meta.label}</span>
          <CardTitle>{insight.title}</CardTitle>
        </div>
        <div className="flex items-center gap-1">
          {insight.is_mock && <DemoBadge />}
          {!insight.is_dismissed && (
            <Button size="icon-sm" variant="ghost" aria-label={`Dismiss "${insight.title}"`} onClick={() => dismiss.mutate(insight.id)}><X /></Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-sm">{insight.body}</p>
        {insight.evidence.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">{insight.evidence.map((e) => <li key={e} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{e}</li>)}</ul>
        )}
        <p className="text-xs text-muted-foreground">Period {formatDate(insight.period_start)} – {formatDate(insight.period_end)} · generated {formatRelative(insight.created_at)}</p>
      </CardContent>
    </Card>
  )
}

function AcceptanceTable() {
  const status = useAIStatus()
  const rows = status.data?.acceptance ?? []
  return (
    <Card>
      <CardHeader>
        <CardTitle>How often people accept AI suggestions</CardTitle>
        <CardDescription>Last 90 days, by suggestion type and prompt version. Auto-applied suggestions are excluded from the rate.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {status.isPending ? <div className="p-4"><Skeleton className="h-24" /></div> : rows.length === 0 ? (
          <p className="px-6 pb-4 text-sm text-muted-foreground">No suggestions yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Suggestion</TableHead><TableHead className="hidden md:table-cell">Prompt</TableHead>
                <TableHead className="text-right">Accepted</TableHead><TableHead className="text-right">Overridden</TableHead>
                <TableHead className="text-right">Rejected</TableHead><TableHead className="text-right">Pending</TableHead>
                <TableHead className="text-right">Acceptance</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={`${r.type}-${r.prompt_version}-${r.is_mock}`}>
                  <TableCell>{TYPE_LABEL[r.type as keyof typeof TYPE_LABEL] ?? r.type} {r.is_mock && <DemoBadge className="ml-1" />}</TableCell>
                  <TableCell className="hidden font-mono text-xs md:table-cell">{r.prompt_version}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.accepted}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.overridden}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.rejected}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.pending}</TableCell>
                  <TableCell className="text-right font-medium tabular-nums">{r.acceptance_rate === null ? '—' : `${Math.round(r.acceptance_rate * 100)}%`}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

export function InsightsPage() {
  const qc = useQueryClient()
  const [showDismissed, setShowDismissed] = useState(false)
  const [days, setDays] = useState(30)
  const insights = useInsights(showDismissed)
  const generate = useGenerateInsights()
  const [waiting, setWaiting] = useState(false)
  const status = useAIStatus()

  const start = async () => {
    setWaiting(true)
    try {
      const done = await waitForAnalysis((await generate.mutateAsync(days)).id)
      void qc.invalidateQueries({ queryKey: ['ai', 'insights'] })
      if (done.status === 'failed') toast.error(`Insights could not be generated: ${done.error}`)
      else toast.success('Insights updated')
    } catch (e) {
      toast.error(firstErrorMessage(e, e instanceof Error ? e.message : undefined))
    } finally {
      setWaiting(false)
    }
  }
  const busy = generate.isPending || waiting

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Insights"
        description="Recurring issues, patterns and deadline risks found in your ticket data. Generated daily and on demand."
        actions={
          <>
            <NativeSelect aria-label="Insight period" className="w-36" value={String(days)} onChange={(e) => setDays(Number(e.target.value))}>
              <option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option>
            </NativeSelect>
            <Button onClick={start} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Sparkles />} {busy ? 'Generating…' : 'Generate now'}</Button>
          </>
        }
      />
      {status.data?.mock_mode && (
        <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <span>AI is running in demo mode: insights come from simple rules over your real statistics, not a language model. Configure <code className="font-mono">AI_PROVIDER</code> on the server to use a real model.</span>
        </div>
      )}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{showDismissed ? 'Dismissed insights' : 'Current insights'}</h2>
        <Button variant="ghost" size="sm" onClick={() => setShowDismissed((v) => !v)}>{showDismissed ? 'Show current' : 'Show dismissed'}</Button>
      </div>
      {insights.isPending ? <div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-36" /><Skeleton className="h-36" /></div> :
        insights.isError ? <ErrorState error={insights.error} onRetry={() => insights.refetch()} /> :
        insights.data.count === 0 ? (
          <EmptyState icon={BrainCircuit} title={showDismissed ? 'Nothing dismissed' : 'No insights yet'} description={showDismissed ? undefined : 'Generate insights to analyse recent tickets.'} />
        ) : <div className="grid gap-4 md:grid-cols-2">{insights.data.results.map((i) => <InsightCard key={i.id} insight={i} />)}</div>}
      <AcceptanceTable />
    </div>
  )
}
