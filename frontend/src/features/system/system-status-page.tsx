import { Database, Radio, RefreshCw, Server, Sparkles, Zap } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '@/components/common/page-header'
import { ErrorState } from '@/components/common/states'
import { type Health, StatusDot } from '@/components/common/status-indicator'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useHealth, useMeta, useReadiness } from '@/lib/api/system'
import { useSocketStatus } from '@/lib/realtime/use-socket-status'

function ServiceRow({ icon: Icon, name, health, detail }: { icon: LucideIcon; name: string; health: Health; detail: string }) {
  const label = { ok: 'Operational', warning: 'Degraded', error: 'Down', unknown: 'Checking' }[health]
  return (
    <li className="flex items-center gap-3 py-3">
      <Icon className="size-4 text-muted-foreground" aria-hidden />
      <span className="flex-1 text-sm font-medium">{name}</span>
      <span className="hidden text-xs text-muted-foreground tabular-nums sm:inline">{detail}</span>
      <span className="flex w-28 items-center justify-end gap-2 text-sm">
        <StatusDot health={health} /> {label}
      </span>
    </li>
  )
}

export function SystemStatusPage() {
  const queryClient = useQueryClient()
  const health = useHealth()
  const readiness = useReadiness()
  const meta = useMeta()
  const socket = useSocketStatus()

  const checks = readiness.data?.checks ?? {}
  const depHealth = (name: string): Health =>
    readiness.isError ? 'error' : !readiness.data ? 'unknown' : checks[name]?.status === 'ok' ? 'ok' : 'error'
  const latency = (name: string) => (checks[name] ? `${checks[name].latency_ms.toFixed(1)} ms` : '—')

  return (
    <div className="space-y-6">
      <PageHeader
        title="System status"
        description="Live health of platform services, reported by the backend."
        actions={
          <Button variant="outline" size="sm" onClick={() => queryClient.invalidateQueries({ queryKey: ['system'] })}>
            <RefreshCw /> Refresh
          </Button>
        }
      />

      {health.isError ? (
        <ErrorState error={health.error} onRetry={() => health.refetch()} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Services</CardTitle>
            </CardHeader>
            <CardContent>
              {health.isPending ? (
                <div className="space-y-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
              ) : (
                <ul className="divide-y">
                  <ServiceRow icon={Server} name="API" health="ok" detail={`v${health.data.version}`} />
                  <ServiceRow icon={Database} name="PostgreSQL" health={depHealth('database')} detail={latency('database')} />
                  <ServiceRow icon={Zap} name="Redis" health={depHealth('redis')} detail={latency('redis')} />
                  <ServiceRow
                    icon={Radio}
                    name="Real-time (WebSocket)"
                    health={socket === 'open' ? 'ok' : socket === 'connecting' ? 'unknown' : 'error'}
                    detail={socket}
                  />
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Environment</CardTitle>
            </CardHeader>
            <CardContent>
              {meta.isPending ? (
                <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-5 w-full" />)}</div>
              ) : meta.isError ? (
                <p className="text-sm text-muted-foreground">Environment details unavailable.</p>
              ) : (
                <dl className="space-y-3 text-sm">
                  <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Version</dt><dd className="font-mono">{meta.data.version}</dd></div>
                  <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Environment</dt><dd className="capitalize">{meta.data.environment}</dd></div>
                  <div className="flex items-center justify-between gap-4">
                    <dt className="flex items-center gap-1.5 text-muted-foreground"><Sparkles className="size-3.5" /> AI provider</dt>
                    <dd className="flex items-center gap-2">
                      <span className="font-mono">{meta.data.ai_provider}</span>
                      {meta.data.ai_mock_mode && <Badge variant="outline">Demo mode</Badge>}
                    </dd>
                  </div>
                  {meta.data.ai_mock_mode && (
                    <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                      AI results come from the offline mock provider and are labelled as demo output. Configure
                      <code className="mx-1 font-mono">AI_PROVIDER</code> on the server to use a real model.
                    </p>
                  )}
                </dl>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
