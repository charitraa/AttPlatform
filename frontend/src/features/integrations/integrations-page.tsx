import { ChevronRight, Plug, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api/client'
import { formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { cn } from '@/lib/utils'
import { type Connector, useCatalog, useIntegrationMutations, useIntegrations } from './api'
import { ConnectorFields, HealthDot, SecretOnceDialog } from './components'
import { fieldErrors } from './field-errors'

const KIND_LABEL: Record<string, string> = { webhook: 'Webhooks', inbound: 'Inbound', sms: 'SMS', whatsapp: 'WhatsApp', rest_api: 'REST' }

function AddDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const catalog = useCatalog()
  const { create } = useIntegrationMutations()
  const [connector, setConnector] = useState<Connector | null>(null)
  const [name, setName] = useState('')
  const [config, setConfig] = useState<Record<string, string>>({})
  const [secrets, setSecrets] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [generated, setGenerated] = useState<{ id: string; secret: string } | null>(null)

  if (generated) {
    return <SecretOnceDialog title="Inbound signing secret" secret={generated.secret} onClose={() => { onClose(); navigate(`/integrations/${generated.id}`) }} />
  }
  const submit = async () => {
    if (!connector) return
    setError(null); setErrors({})
    try {
      const created = await create.mutateAsync({
        kind: connector.kind, provider: connector.provider, name: name.trim() || connector.label,
        config: Object.fromEntries(Object.entries(config).filter(([, v]) => v)), secrets: Object.fromEntries(Object.entries(secrets).filter(([, v]) => v)),
      })
      toast.success('Integration added')
      const secret = created.generated_secrets?.signing_secret
      if (secret) setGenerated({ id: created.id, secret })
      else { onClose(); navigate(`/integrations/${created.id}`) }
    } catch (e) {
      setErrors(e instanceof ApiError ? fieldErrors(e.details) : {})
      setError(firstErrorMessage(e))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{connector ? connector.label : 'Add an integration'}</DialogTitle>
          <DialogDescription>{connector ? connector.description : 'Choose what to connect.'}</DialogDescription>
        </DialogHeader>
        {!connector ? (
          catalog.isPending ? <Skeleton className="h-48" /> : (
            <ul className="grid gap-2">
              {catalog.data?.connectors.map((c) => (
                <li key={`${c.kind}/${c.provider}`}>
                  <button type="button" className="w-full rounded-lg border p-3 text-left transition-colors hover:bg-muted/50"
                    onClick={() => { setConnector(c); setName(c.label) }}>
                    <span className="flex items-center gap-2 font-medium">{c.label} <Badge variant="outline">{KIND_LABEL[c.kind] ?? c.kind}</Badge></span>
                    <span className="mt-0.5 block text-sm text-muted-foreground">{c.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : (
          <div className="space-y-4">
            <FormError message={error} />
            <Field label="Name" error={errors.name}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <ConnectorFields fields={connector.fields} values={config} errors={errors} onChange={(k, v) => setConfig({ ...config, [k]: v })} />
            {connector.secrets.length > 0 && (
              <fieldset className="space-y-3 rounded-lg border p-3">
                <legend className="px-1 text-sm font-medium">Credentials</legend>
                <p className="text-xs text-muted-foreground">Stored encrypted. They're never shown again or sent to the browser.</p>
                <ConnectorFields secret fields={connector.secrets} values={secrets} errors={errors} onChange={(k, v) => setSecrets({ ...secrets, [k]: v })} />
              </fieldset>
            )}
            {connector.generated_secrets.length > 0 && <p className="text-xs text-muted-foreground">A signing secret is generated for you and shown once after saving.</p>}
          </div>
        )}
        <DialogFooter>
          {connector && <Button variant="ghost" className="mr-auto" onClick={() => setConnector(null)}>Back</Button>}
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          {connector && <Button onClick={submit} disabled={create.isPending}>Add integration</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function IntegrationsPage() {
  const list = useIntegrations()
  const [adding, setAdding] = useState(false)
  return (
    <div className="space-y-5">
      <PageHeader title="Integrations" description="Send events to your systems, receive tickets from them, and connect SMS and WhatsApp."
        actions={<Button onClick={() => setAdding(true)}><Plus /> Add integration</Button>} />
      {list.isPending ? <Skeleton className="h-40" /> : list.isError ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> :
        list.data.length === 0 ? (
          <EmptyState icon={Plug} title="No integrations yet" description="Start with outbound webhooks to keep another system in sync with tickets and work orders."
            action={<Button onClick={() => setAdding(true)}><Plus /> Add integration</Button>} />
        ) : (
          <ul className="grid gap-3 md:grid-cols-2">
            {list.data.map((i) => (
              <li key={i.id}>
                <Link to={`/integrations/${i.id}`} className={cn('flex h-full items-start gap-3 rounded-xl border bg-card p-4 transition-colors hover:bg-muted/40', !i.is_enabled && 'opacity-70')}>
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{i.name}</span>
                      <Badge variant="outline">{KIND_LABEL[i.kind] ?? i.kind}</Badge>
                      {!i.is_enabled && <Badge variant="secondary">Off</Badge>}
                    </div>
                    <p className="text-sm text-muted-foreground">{i.label}{i.endpoint_count !== null && ` · ${i.endpoint_count} endpoint(s)`}</p>
                    <div className="flex flex-wrap items-center gap-x-3 text-xs">
                      <HealthDot health={i.health} />
                      {i.health === 'error' && i.last_error && <span className="truncate text-destructive" title={i.last_error}>{i.last_error}</span>}
                      {i.health === 'ok' && i.last_success_at && <span className="text-muted-foreground">last success {formatRelative(i.last_success_at)}</span>}
                    </div>
                  </div>
                  <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      {adding && <AddDialog onClose={() => setAdding(false)} />}
    </div>
  )
}
