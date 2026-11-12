import { ArrowLeft, PlugZap, Plus, RefreshCw, RotateCcw, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState } from '@/components/common/states'
import { CheckboxField } from '@/components/forms/checkbox-field'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api/client'
import { formatDateTime, formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { cn } from '@/lib/utils'
import {
  type Delivery, type Integration, useCatalog, useDeliveries, useEndpoints, useInboundEvents, useIntegration,
  useIntegrationMutations, useLogs,
} from './api'
import { ConnectorFields, CopyField, HealthDot, SecretOnceDialog } from './components'
import { fieldErrors } from './field-errors'

function Pager({ data, page, setPage }: { data?: { next: string | null; previous: string | null }; page: number; setPage: (n: number) => void }) {
  if (!data || (!data.next && !data.previous)) return null
  return (
    <div className="flex justify-end gap-2">
      <Button variant="outline" size="sm" disabled={!data.previous} onClick={() => setPage(page - 1)}>Previous</Button>
      <Button variant="outline" size="sm" disabled={!data.next} onClick={() => setPage(page + 1)}>Next</Button>
    </div>
  )
}

// ------------------------------------------------------------------ settings
function Settings({ i }: { i: Integration }) {
  const navigate = useNavigate()
  const catalog = useCatalog()
  const m = useIntegrationMutations(i.id)
  const connector = catalog.data?.connectors.find((c) => c.kind === i.kind && c.provider === i.provider)
  const [name, setName] = useState(i.name)
  const [config, setConfig] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(i.config).map(([k, v]) => [k, String(v ?? '')])))
  const [secrets, setSecrets] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [rotated, setRotated] = useState<string | null>(null)
  const [to, setTo] = useState('')
  const [text, setText] = useState('Test message from ATT Platform')
  const [template, setTemplate] = useState('')

  const save = async () => {
    setError(null); setErrors({})
    try {
      await m.update.mutateAsync({ name, config: Object.fromEntries(Object.entries(config).filter(([, v]) => v)), secrets })
      setSecrets({})
      toast.success('Saved')
    } catch (e) {
      setErrors(e instanceof ApiError ? fieldErrors(e.details) : {})
      setError(firstErrorMessage(e))
    }
  }
  const test = () => m.test.mutate(undefined, {
    onSuccess: (r) => (r.ok ? toast.success(r.message) : toast.error(r.message)), onError: (e) => toast.error(firstErrorMessage(e)),
  })
  const remove = () => {
    if (!window.confirm(`Delete “${i.name}”? Its endpoints, deliveries and logs are deleted too.`)) return
    m.remove.mutate(undefined, { onSuccess: () => { toast.success('Integration deleted'); navigate('/integrations') }, onError: (e) => toast.error(firstErrorMessage(e)) })
  }
  const example = i.inbound_url ? `BODY='{"id":"msg-001","from":{"email":"customer@example.com"},"subject":"Printer jammed","body":"Third floor printer is jammed."}'
TS=$(date +%s)
SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SIGNING_SECRET" -hex | sed 's/^.* //')
curl -X POST '${i.inbound_url}' -H 'Content-Type: application/json' \\
  -H "X-ATT-Signature: t=$TS,v1=$SIG" -d "$BODY"` : ''

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <Card>
        <CardHeader><CardTitle>Settings</CardTitle><CardDescription>{connector?.description}</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          <FormError message={error} />
          <Field label="Name" error={errors.name}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          {connector && <ConnectorFields fields={connector.fields} values={config} errors={errors} onChange={(k, v) => setConfig({ ...config, [k]: v })} />}
          {connector && connector.secrets.length > 0 && (
            <fieldset className="space-y-3 rounded-lg border p-3">
              <legend className="px-1 text-sm font-medium">Credentials</legend>
              <ConnectorFields secret fields={connector.secrets} values={secrets} errors={errors} configured={i.credentials}
                onChange={(k, v) => setSecrets({ ...secrets, [k]: v })} />
            </fieldset>
          )}
          <div className="flex flex-wrap justify-between gap-2">
            <Button variant="ghost" className="text-destructive" onClick={remove}><Trash2 /> Delete</Button>
            <Button onClick={save} disabled={m.update.isPending}>Save changes</Button>
          </div>
        </CardContent>
      </Card>
      <div className="space-y-6">
        <Card>
          <CardHeader><CardTitle>Status</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <HealthDot health={i.health} />
            {i.last_error && i.health === 'error' && <p className="text-xs break-words text-destructive">{i.last_error} · {i.last_error_at && formatRelative(i.last_error_at)}</p>}
            {i.last_success_at && <p className="text-xs text-muted-foreground">Last success {formatRelative(i.last_success_at)}</p>}
            <CheckboxField label="Enabled" checked={i.is_enabled} disabled={m.update.isPending}
              description="Turned off, nothing is sent or accepted."
              onChange={(e) => m.update.mutate({ is_enabled: e.target.checked }, { onError: (err) => toast.error(firstErrorMessage(err)) })} />
            <Button variant="outline" className="w-full" onClick={test} disabled={m.test.isPending}><PlugZap /> {m.test.isPending ? 'Testing…' : 'Test connection'}</Button>
          </CardContent>
        </Card>
        {connector?.can_send && (
          <Card>
            <CardHeader><CardTitle>Send a test message</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Field label="To" description="E.164, e.g. +9779812345678"><Input value={to} onChange={(e) => setTo(e.target.value)} /></Field>
              {i.kind === 'whatsapp'
                ? <Field label="Approved template name"><Input value={template} onChange={(e) => setTemplate(e.target.value)} /></Field>
                : <Field label="Text"><Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} /></Field>}
              <Button variant="outline" className="w-full" disabled={!to || m.sendTest.isPending}
                onClick={() => m.sendTest.mutate({ to, text, template }, { onSuccess: () => toast.success('Sent'), onError: (e) => toast.error(firstErrorMessage(e)) })}>
                <Send /> Send
              </Button>
            </CardContent>
          </Card>
        )}
        {i.inbound_url && (
          <Card>
            <CardHeader><CardTitle>Receiving</CardTitle><CardDescription>POST signed JSON to this URL.</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              <CopyField value={i.inbound_url} label="inbound URL" />
              <p className="text-xs text-muted-foreground">Signing secret {i.credentials.signing_secret?.configured ? `saved (${i.credentials.signing_secret.hint})` : 'missing'}.</p>
              <Button variant="outline" size="sm" onClick={() => {
                if (!window.confirm('Rotate the signing secret? The current one stops working immediately.')) return
                m.rotate.mutate(undefined, { onSuccess: (r) => setRotated(r.signing_secret), onError: (e) => toast.error(firstErrorMessage(e)) })
              }}><RotateCcw /> Rotate secret</Button>
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Example request</summary>
                <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-2 text-[11px] leading-relaxed">{example}</pre>
                <p className="mt-1 text-muted-foreground">Mention a reference like TCK-000042 in the subject to add a reply to that ticket. Re-sending the same <code>id</code> is ignored.</p>
              </details>
            </CardContent>
          </Card>
        )}
      </div>
      {rotated && <SecretOnceDialog title="New signing secret" secret={rotated} onClose={() => setRotated(null)} />}
    </div>
  )
}

// ----------------------------------------------------------------- endpoints
function EndpointDialog({ integrationId, onClose, onSecret }: { integrationId: string; onClose: () => void; onSecret: (s: string) => void }) {
  const catalog = useCatalog()
  const { addEndpoint } = useIntegrationMutations(integrationId)
  const [url, setUrl] = useState('https://')
  const [description, setDescription] = useState('')
  const [events, setEvents] = useState<string[]>(['ticket.created', 'ticket.status_changed'])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const submit = async () => {
    setError(null); setErrors({})
    try {
      const e = await addEndpoint.mutateAsync({ url, events, description })
      onClose()
      if (e.signing_secret) onSecret(e.signing_secret)
    } catch (err) {
      setErrors(err instanceof ApiError ? fieldErrors(err.details) : {})
      setError(firstErrorMessage(err))
    }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New endpoint</DialogTitle>
          <DialogDescription>Must be a public https URL. Private and internal network addresses are refused.</DialogDescription>
        </DialogHeader>
        <FormError message={error} />
        <Field label="URL" error={errors.url}><Input type="url" value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Field label="Description (optional)"><Input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Events</legend>
          {errors.events && <p role="alert" className="text-xs text-destructive">{errors.events}</p>}
          <div className="grid gap-2 sm:grid-cols-2">
            {catalog.data?.events.map((ev) => (
              <CheckboxField key={ev.type} label={ev.type} description={ev.label} checked={events.includes(ev.type)}
                onChange={() => setEvents((cur) => (cur.includes(ev.type) ? cur.filter((x) => x !== ev.type) : [...cur, ev.type]))} />
            ))}
          </div>
        </fieldset>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={!events.length || addEndpoint.isPending}>Add endpoint</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Endpoints({ i }: { i: Integration }) {
  const endpoints = useEndpoints(i.id, true)
  const m = useIntegrationMutations(i.id)
  const [adding, setAdding] = useState(false)
  const [secret, setSecret] = useState<string | null>(null)
  if (endpoints.isPending) return <Skeleton className="h-32" />
  if (endpoints.isError) return <ErrorState error={endpoints.error} onRetry={() => endpoints.refetch()} />
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Each delivery is signed with <code className="text-xs">X-ATT-Signature: t=…,v1=HMAC-SHA256(secret, "t.body")</code> and retried for about 15 hours.</p>
        <Button onClick={() => setAdding(true)}><Plus /> Add endpoint</Button>
      </div>
      {endpoints.data.length === 0 ? <EmptyState icon={Send} title="No endpoints" description="Add a URL to start receiving events." /> : (
        <ul className="space-y-2">
          {endpoints.data.map((e) => (
            <li key={e.id} className={cn('rounded-xl border bg-card p-4', !e.is_active && 'opacity-70')}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-mono text-sm break-all">{e.url}</p>
                  {e.description && <p className="text-sm text-muted-foreground">{e.description}</p>}
                  <div className="mt-1.5 flex flex-wrap gap-1">{e.events.map((ev) => <Badge key={ev} variant="outline" className="font-mono text-[11px]">{ev}</Badge>)}</div>
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    {e.stats.last_at ? <>Last delivery {e.stats.last_status} {formatRelative(e.stats.last_at)}</> : 'No deliveries yet'}
                    {e.stats.failed > 0 && <span className="text-destructive"> · {e.stats.failed} failed</span>}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <CheckboxField label="Active" checked={e.is_active} onChange={(ev) => m.updateEndpoint.mutate({ endpointId: e.id, is_active: ev.target.checked })} />
                  <Button variant="ghost" size="icon" aria-label="Rotate signing secret" onClick={() => {
                    if (window.confirm('Rotate this endpoint\'s signing secret? Update your receiver right away.')) {
                      m.rotateEndpoint.mutate(e.id, { onSuccess: (r) => setSecret(r.signing_secret) })
                    }
                  }}><RotateCcw /></Button>
                  <Button variant="ghost" size="icon" aria-label={`Delete ${e.url}`} onClick={() => {
                    if (window.confirm(`Delete ${e.url}?`)) m.removeEndpoint.mutate(e.id, { onSuccess: () => toast.success('Endpoint deleted') })
                  }}><Trash2 /></Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {adding && <EndpointDialog integrationId={i.id} onClose={() => setAdding(false)} onSecret={setSecret} />}
      {secret && <SecretOnceDialog title="Endpoint signing secret" secret={secret} onClose={() => setSecret(null)} />}
    </div>
  )
}

const DELIVERY_TONE: Record<Delivery['status'], string> = {
  succeeded: 'text-success', retrying: 'text-warning', pending: 'text-muted-foreground', failed: 'text-destructive',
}

function Deliveries({ i }: { i: Integration }) {
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const list = useDeliveries(i.id, { status, page }, true)
  const { redeliver } = useIntegrationMutations(i.id)
  return (
    <div className="space-y-3">
      <NativeSelect aria-label="Delivery status" className="w-44" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
        <option value="">All deliveries</option><option value="failed">Failed</option><option value="retrying">Retrying</option><option value="succeeded">Delivered</option>
      </NativeSelect>
      {list.isPending ? <Skeleton className="h-40" /> : list.isError ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> :
        list.data.count === 0 ? <EmptyState icon={Send} title="No deliveries" description="Events appear here as they're sent." /> : (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader><TableRow><TableHead>Event</TableHead><TableHead>Status</TableHead><TableHead className="hidden md:table-cell">Endpoint</TableHead><TableHead>Attempts</TableHead><TableHead>When</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                {list.data.results.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="font-mono text-xs">{d.event_type}</TableCell>
                    <TableCell>
                      <span className={cn('text-sm font-medium', DELIVERY_TONE[d.status])}>{d.status === 'succeeded' ? 'Delivered' : d.status}</span>
                      <span className="block text-xs text-muted-foreground">{d.response_code ? `HTTP ${d.response_code}` : d.error}{d.next_retry_at && ` · next ${formatRelative(d.next_retry_at)}`}</span>
                    </TableCell>
                    <TableCell className="hidden max-w-[14rem] truncate font-mono text-xs md:table-cell" title={d.url}>{d.url}</TableCell>
                    <TableCell className="tabular-nums">{d.attempts}</TableCell>
                    <TableCell className="text-xs text-muted-foreground" title={formatDateTime(d.created_at)}>{formatRelative(d.created_at)}</TableCell>
                    <TableCell>
                      {(d.status === 'failed' || d.status === 'retrying') && (
                        <Button size="sm" variant="outline" disabled={redeliver.isPending}
                          onClick={() => redeliver.mutate(d.id, { onSuccess: () => toast.success('Queued for redelivery') })}><RefreshCw /> Retry now</Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      <Pager data={list.data} page={page} setPage={setPage} />
    </div>
  )
}

function Inbound({ i }: { i: Integration }) {
  const [page, setPage] = useState(1)
  const list = useInboundEvents(i.id, page, true)
  if (list.isPending) return <Skeleton className="h-40" />
  if (list.isError) return <ErrorState error={list.error} onRetry={() => list.refetch()} />
  if (list.data.count === 0) return <EmptyState icon={Send} title="Nothing received yet" description="Accepted messages appear here with what they became." />
  return (
    <div className="space-y-3">
      <ul className="divide-y rounded-xl border bg-card">
        {list.data.results.map((e) => {
          const ref = typeof e.result.reference === 'string' ? e.result.reference : null
          const ticketId = typeof e.result.ticket_id === 'string' ? e.result.ticket_id : null
          return (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <div className="min-w-0">
                <span className="font-mono text-xs text-muted-foreground">{e.external_id}</span>
                <p>{e.status === 'processed' && ticketId
                  ? <>{e.result.action === 'comment' ? 'Reply added to ' : 'Created '}<Link className="text-primary hover:underline" to={`/tickets/${ticketId}`}>{ref}</Link></>
                  : <span className={cn(e.status === 'failed' && 'text-destructive', e.status === 'ignored' && 'text-warning')}>{e.status}{e.error && `: ${e.error}`}</span>}</p>
              </div>
              <time className="text-xs text-muted-foreground" dateTime={e.created_at}>{formatRelative(e.created_at)}</time>
            </li>
          )
        })}
      </ul>
      <Pager data={list.data} page={page} setPage={setPage} />
    </div>
  )
}

function Logs({ i }: { i: Integration }) {
  const [page, setPage] = useState(1)
  const logs = useLogs(i.id, page)
  if (logs.isPending) return <Skeleton className="h-40" />
  if (logs.isError) return <ErrorState error={logs.error} onRetry={() => logs.refetch()} />
  if (logs.data.count === 0) return <EmptyState icon={Send} title="No activity yet" />
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-xl border bg-card">
        <Table>
          <TableHeader><TableRow><TableHead>When</TableHead><TableHead>Operation</TableHead><TableHead>Result</TableHead><TableHead className="hidden md:table-cell">Details</TableHead></TableRow></TableHeader>
          <TableBody>
            {logs.data.results.map((l) => (
              <TableRow key={l.id}>
                <TableCell className="text-xs whitespace-nowrap text-muted-foreground" title={formatDateTime(l.created_at)}>{formatRelative(l.created_at)}</TableCell>
                <TableCell className="text-sm">{l.direction === 'inbound' ? '← ' : '→ '}{l.operation}</TableCell>
                <TableCell><span className={cn('text-sm font-medium', l.status === 'ok' ? 'text-success' : 'text-destructive')}>{l.status === 'ok' ? 'OK' : 'Error'}</span>{l.duration_ms !== null && <span className="ml-1 text-xs text-muted-foreground">{l.duration_ms} ms</span>}</TableCell>
                <TableCell className="hidden max-w-[24rem] text-xs break-words text-muted-foreground md:table-cell">{[l.request_summary, l.response_summary, l.error].filter(Boolean).join(' · ')}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Pager data={logs.data} page={page} setPage={setPage} />
    </div>
  )
}

export function IntegrationDetailPage() {
  const { id = '' } = useParams()
  const q = useIntegration(id)
  if (q.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-64" /></div>
  if (q.isError) {
    const missing = q.error instanceof ApiError && q.error.status === 404
    return <ErrorState error={missing ? new Error("This integration doesn't exist.") : q.error} onRetry={missing ? undefined : () => q.refetch()} />
  }
  const i = q.data
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Link to="/integrations" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Integrations</Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">{i.name}</h1>
          <Badge variant="outline">{i.label}</Badge>
          {!i.is_enabled && <Badge variant="secondary">Off</Badge>}
        </div>
      </div>
      <Tabs defaultValue="settings">
        <TabsList>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          {i.kind === 'webhook' && <TabsTrigger value="endpoints">Endpoints</TabsTrigger>}
          {i.kind === 'webhook' && <TabsTrigger value="deliveries">Deliveries</TabsTrigger>}
          {(i.kind === 'inbound' || i.kind === 'email') && <TabsTrigger value="inbound">Received</TabsTrigger>}
          <TabsTrigger value="logs">Activity log</TabsTrigger>
        </TabsList>
        <TabsContent value="settings" className="pt-4"><Settings key={i.updated_at} i={i} /></TabsContent>
        {i.kind === 'webhook' && <TabsContent value="endpoints" className="pt-4"><Endpoints i={i} /></TabsContent>}
        {i.kind === 'webhook' && <TabsContent value="deliveries" className="pt-4"><Deliveries i={i} /></TabsContent>}
        {(i.kind === 'inbound' || i.kind === 'email') && <TabsContent value="inbound" className="pt-4"><Inbound i={i} /></TabsContent>}
        <TabsContent value="logs" className="pt-4"><Logs i={i} /></TabsContent>
      </Tabs>
    </div>
  )
}
