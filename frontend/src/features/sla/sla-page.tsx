import { CalendarClock, Pencil, Plus, ShieldCheck, Timer, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
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
import { useCategories } from '@/features/tickets/api'
import { CHANNEL_LABEL, PRIORITIES, PRIORITY_LABEL, type Priority } from '@/features/tickets/constants'
import { firstErrorMessage } from '@/lib/forms'
import { useCan } from '@/stores/auth'
import {
  type BusinessHours, type Policy, type Target, WEEKDAYS, WEEKDAY_LABEL, useBusinessHours, useHoursMutations,
  usePolicies, usePolicyMutations, useSLAReport,
} from './api'
import { minutesLabel } from './format'

const TIERS = { standard: 'Standard', premium: 'Premium', enterprise: 'Enterprise' } as const
const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

// ------------------------------------------------------------------- report
function Report() {
  const [days, setDays] = useState(30)
  const report = useSLAReport(days)
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <NativeSelect aria-label="Period" className="w-40" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </NativeSelect>
      </div>
      {report.isPending ? <Skeleton className="h-48" /> : report.isError ? <ErrorState error={report.error} onRetry={() => report.refetch()} /> : (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
              <p className="text-3xl font-semibold tabular-nums">{pct(report.data.resolution_compliance)}</p>
              <p className="text-sm text-muted-foreground">of resolution targets met, for tickets opened in the period that have finished or breached.</p>
            </CardContent>
          </Card>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Priority</TableHead><TableHead className="text-right">Tickets</TableHead>
                  <TableHead className="text-right">Response met</TableHead><TableHead className="text-right">Resolution met</TableHead>
                  <TableHead className="text-right">Breached</TableHead><TableHead className="text-right">At risk now</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...PRIORITIES].reverse().map((p) => {
                  const r = report.data.by_priority[p]
                  if (!r) return null
                  return (
                    <TableRow key={p}>
                      <TableCell>{PRIORITY_LABEL[p]}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.tickets}</TableCell>
                      <TableCell className="text-right tabular-nums">{pct(r.response_compliance)}</TableCell>
                      <TableCell className="text-right tabular-nums">{pct(r.resolution_compliance)}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.resolution_breached + r.response_breached}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.at_risk}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  )
}

// ----------------------------------------------------------------- policies
type TargetDraft = Record<Priority, { on: boolean; response: string; resolution: string; warn: string }>

function PolicyDialog({ policy, hours, onClose }: { policy: Policy | null; hours: BusinessHours[]; onClose: () => void }) {
  const { save } = usePolicyMutations()
  const categories = useCategories()
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState(() => ({
    name: policy?.name ?? '', description: policy?.description ?? '', is_active: policy?.is_active ?? true,
    business_hours: policy ? policy.business_hours ?? '' : hours[0]?.id ?? '', priority_order: String(policy?.priority_order ?? 100),
    escalate_on_breach: policy?.escalate_on_breach ?? true,
    categories: policy?.conditions.categories ?? [], customer_tiers: policy?.conditions.customer_tiers ?? [],
    channels: policy?.conditions.channels ?? [],
  }))
  const [targets, setTargets] = useState<TargetDraft>(() => Object.fromEntries(PRIORITIES.map((p) => {
    const t = policy?.targets.find((x) => x.priority === p)
    return [p, { on: !!t || !policy, response: String(t?.first_response_minutes ?? 60), resolution: String(t?.resolution_minutes ?? 480), warn: String(t?.warning_threshold_pct ?? 80) }]
  })) as TargetDraft)
  const isDefault = !!policy?.is_default
  const toggle = (key: 'categories' | 'customer_tiers' | 'channels', v: string) =>
    setForm((f) => ({ ...f, [key]: f[key].includes(v) ? f[key].filter((x) => x !== v) : [...f[key], v] }))

  const submit = async () => {
    setError(null)
    const body: Record<string, unknown> = {
      id: policy?.id, name: form.name, description: form.description, is_active: form.is_active,
      business_hours: form.business_hours || null, priority_order: Number(form.priority_order), escalate_on_breach: form.escalate_on_breach,
      conditions: { categories: form.categories, customer_tiers: form.customer_tiers, channels: form.channels },
      targets: PRIORITIES.filter((p) => targets[p].on).map((p): Target => ({
        priority: p, first_response_minutes: Number(targets[p].response), resolution_minutes: Number(targets[p].resolution),
        warning_threshold_pct: Number(targets[p].warn),
      })),
    }
    try {
      await save.mutateAsync(body)
      toast.success(policy ? 'Policy saved' : 'Policy created')
      onClose()
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{policy ? `Edit ${policy.name}` : 'New SLA policy'}</DialogTitle>
          <DialogDescription>Targets are working time on the chosen calendar. Saved changes apply to new tickets; running clocks keep the targets they started with.</DialogDescription>
        </DialogHeader>
        <FormError message={error} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Working hours">
            <NativeSelect value={form.business_hours} onChange={(e) => setForm({ ...form, business_hours: e.target.value })}>
              {hours.map((h) => <option key={h.id} value={h.id}>{h.name} ({h.timezone})</option>)}
              <option value="">24/7 (clock never stops)</option>
            </NativeSelect>
          </Field>
          <Field label="Description" className="sm:col-span-2"><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Targets</legend>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1 font-medium">Priority</th><th className="py-1 font-medium">First response (min)</th><th className="py-1 font-medium">Resolution (min)</th><th className="py-1 font-medium">Warn at %</th></tr></thead>
              <tbody>
                {[...PRIORITIES].reverse().map((p) => {
                  const t = targets[p]
                  const set = (patch: Partial<TargetDraft[Priority]>) => setTargets((all) => ({ ...all, [p]: { ...all[p], ...patch } }))
                  return (
                    <tr key={p}>
                      <td className="py-1 pr-2">
                        <label className="flex items-center gap-2">
                          <input type="checkbox" className="size-4 accent-primary" checked={t.on} disabled={isDefault} onChange={(e) => set({ on: e.target.checked })} />
                          {PRIORITY_LABEL[p]}
                        </label>
                      </td>
                      {(['response', 'resolution', 'warn'] as const).map((k) => (
                        <td key={k} className="py-1 pr-2">
                          <Input type="number" min={1} max={k === 'warn' ? 99 : undefined} className="h-8 w-28" disabled={!t.on}
                            aria-label={`${PRIORITY_LABEL[p]} ${k === 'warn' ? 'warning threshold' : k === 'response' ? 'first response minutes' : 'resolution minutes'}`}
                            value={t[k]} onChange={(e) => set({ [k]: e.target.value })} />
                          {k !== 'warn' && t.on && Number(t[k]) > 0 && <span className="ml-1 text-xs text-muted-foreground">{minutesLabel(Number(t[k]))}</span>}
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {isDefault && <p className="text-xs text-muted-foreground">The default policy covers every priority.</p>}
        </fieldset>

        {!isDefault && (
          <fieldset className="space-y-3">
            <legend className="text-sm font-medium">Applies to <span className="font-normal text-muted-foreground">(leave a group empty to match anything)</span></legend>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1.5"><p className="text-xs text-muted-foreground">Customer tier</p>
                {Object.entries(TIERS).map(([v, l]) => <CheckboxField key={v} label={l} checked={form.customer_tiers.includes(v)} onChange={() => toggle('customer_tiers', v)} />)}
              </div>
              <div className="space-y-1.5"><p className="text-xs text-muted-foreground">Channel</p>
                {Object.entries(CHANNEL_LABEL).map(([v, l]) => <CheckboxField key={v} label={l} checked={form.channels.includes(v)} onChange={() => toggle('channels', v)} />)}
              </div>
              <div className="max-h-48 space-y-1.5 overflow-y-auto"><p className="text-xs text-muted-foreground">Category</p>
                {(categories.data ?? []).map((c) => <CheckboxField key={c.id} label={c.full_name ?? c.name} checked={form.categories.includes(c.id)} onChange={() => toggle('categories', c.id)} />)}
              </div>
            </div>
            <Field label="Evaluation order" description="Lower numbers are checked first; the first matching policy with a target for the ticket's priority wins.">
              <Input type="number" min={0} className="w-32" value={form.priority_order} onChange={(e) => setForm({ ...form, priority_order: e.target.value })} />
            </Field>
          </fieldset>
        )}
        <div className="space-y-2">
          <CheckboxField label="Escalate the ticket when the resolution target is breached" checked={form.escalate_on_breach}
            onChange={(e) => setForm({ ...form, escalate_on_breach: e.target.checked })} />
          {!isDefault && <CheckboxField label="Active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={save.isPending || !form.name.trim()}>Save policy</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Policies() {
  const policies = usePolicies()
  const hours = useBusinessHours()
  const { remove } = usePolicyMutations()
  const canManage = useCan('sla.manage')
  const [editing, setEditing] = useState<Policy | null | 'new'>(null)
  if (policies.isPending || hours.isPending) return <Skeleton className="h-48" />
  if (policies.isError) return <ErrorState error={policies.error} onRetry={() => policies.refetch()} />
  const del = (p: Policy) => {
    if (!window.confirm(`Delete the "${p.name}" policy? Running SLA clocks keep their targets.`)) return
    remove.mutate(p.id, { onSuccess: () => toast.success('Policy deleted'), onError: (e) => toast.error(firstErrorMessage(e)) })
  }
  const ordered = [...policies.data].sort((a, b) => Number(a.is_default) - Number(b.is_default) || a.priority_order - b.priority_order)
  return (
    <div className="space-y-4">
      {canManage && <div className="flex justify-end"><Button onClick={() => setEditing('new')}><Plus /> New policy</Button></div>}
      <ul className="grid gap-4 lg:grid-cols-2">
        {ordered.map((p) => (
          <li key={p.id}>
            <Card className="h-full">
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <CardTitle className="flex flex-wrap items-center gap-2">{p.name}
                      {p.is_default && <Badge variant="secondary">Default</Badge>}
                      {!p.is_active && <Badge variant="outline">Inactive</Badge>}
                    </CardTitle>
                    <CardDescription>{p.business_hours_name ?? '24/7'}{p.description && ` · ${p.description}`}</CardDescription>
                  </div>
                  {canManage && (
                    <div className="flex shrink-0 gap-1">
                      <Button variant="ghost" size="icon" aria-label={`Edit ${p.name}`} onClick={() => setEditing(p)}><Pencil /></Button>
                      {!p.is_default && <Button variant="ghost" size="icon" aria-label={`Delete ${p.name}`} onClick={() => del(p)}><Trash2 /></Button>}
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-muted-foreground"><th className="font-medium">Priority</th><th className="font-medium">Response</th><th className="font-medium">Resolution</th></tr></thead>
                  <tbody>
                    {[...PRIORITIES].reverse().map((pr) => {
                      const t = p.targets.find((x) => x.priority === pr)
                      return <tr key={pr}><td className="py-0.5">{PRIORITY_LABEL[pr]}</td><td>{t ? minutesLabel(t.first_response_minutes) : '—'}</td><td>{t ? minutesLabel(t.resolution_minutes) : '—'}</td></tr>
                    })}
                  </tbody>
                </table>
                {!p.is_default && (
                  <p className="text-xs text-muted-foreground">
                    {[p.conditions.customer_tiers.map((t) => TIERS[t as keyof typeof TIERS] ?? t).join(', '),
                      p.conditions.channels.map((c) => CHANNEL_LABEL[c as keyof typeof CHANNEL_LABEL] ?? c).join(', '),
                      p.conditions.categories.length ? `${p.conditions.categories.length} categor${p.conditions.categories.length === 1 ? 'y' : 'ies'}` : '',
                    ].filter(Boolean).join(' · ') || 'Matches every ticket'} · order {p.priority_order}
                  </p>
                )}
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
      {editing && <PolicyDialog policy={editing === 'new' ? null : editing} hours={hours.data ?? []} onClose={() => setEditing(null)} />}
    </div>
  )
}

// -------------------------------------------------------------------- hours
const fmtDay = (spans: [string, string][] | undefined) => (spans ?? []).map(([a, b]) => `${a}-${b}`).join(', ')
function parseDay(text: string): [string, string][] {
  return text.split(',').map((s) => s.trim()).filter(Boolean).map((s) => {
    const [a = '', b = ''] = s.split('-').map((x) => x.trim())
    return [a, b]
  })
}

function HoursDialog({ hours, onClose }: { hours: BusinessHours | null; onClose: () => void }) {
  const { save } = useHoursMutations()
  const zones = useMemo(() => (typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : []), [])
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState(hours?.name ?? '')
  const [tz, setTz] = useState(hours?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone)
  const [days, setDays] = useState(() => Object.fromEntries(WEEKDAYS.map((d) => [d, hours ? fmtDay(hours.schedule[d]) : d === 'sat' ? '' : '09:00-17:00'])))
  const [holidays, setHolidays] = useState(hours?.holidays.map((h) => `${h.date} ${h.name}`).join('\n') ?? '')
  const submit = async () => {
    setError(null)
    try {
      await save.mutateAsync({
        id: hours?.id, name, timezone: tz,
        schedule: Object.fromEntries(WEEKDAYS.map((d) => [d, parseDay(days[d] ?? '')])),
        holidays: holidays.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
          const [date = '', ...rest] = l.split(/\s+/)
          return { date, name: rest.join(' ') || 'Holiday' }
        }),
      })
      toast.success(hours ? 'Working hours saved' : 'Working hours created')
      onClose()
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{hours ? `Edit ${hours.name}` : 'New working hours'}</DialogTitle>
          <DialogDescription>SLA clocks only run inside these hours. Use 24:00 for midnight at the end of a day.</DialogDescription>
        </DialogHeader>
        <FormError message={error} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Time zone">
            <Input list="sla-timezones" value={tz} onChange={(e) => setTz(e.target.value)} />
          </Field>
          <datalist id="sla-timezones">{zones.map((z) => <option key={z} value={z} />)}</datalist>
        </div>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Weekly hours <span className="font-normal text-muted-foreground">(e.g. 09:00-12:00, 13:00-17:00; empty = closed)</span></legend>
          {WEEKDAYS.map((d) => (
            <div key={d} className="grid grid-cols-[6rem_1fr] items-center gap-2">
              <label htmlFor={`day-${d}`} className="text-sm">{WEEKDAY_LABEL[d]}</label>
              <Input id={`day-${d}`} className="h-8" placeholder="Closed" value={days[d] ?? ''} onChange={(e) => setDays({ ...days, [d]: e.target.value })} />
            </div>
          ))}
        </fieldset>
        <Field label="Holidays" description="One per line: YYYY-MM-DD name">
          <Textarea rows={3} value={holidays} onChange={(e) => setHolidays(e.target.value)} placeholder="2026-12-25 Office closed" />
        </Field>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={save.isPending || !name.trim()}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Hours() {
  const hours = useBusinessHours()
  const { remove } = useHoursMutations()
  const canManage = useCan('sla.manage')
  const [editing, setEditing] = useState<BusinessHours | null | 'new'>(null)
  if (hours.isPending) return <Skeleton className="h-48" />
  if (hours.isError) return <ErrorState error={hours.error} onRetry={() => hours.refetch()} />
  const del = (h: BusinessHours) => {
    if (!window.confirm(`Delete "${h.name}"?`)) return
    remove.mutate(h.id, { onSuccess: () => toast.success('Deleted'), onError: (e) => toast.error(firstErrorMessage(e)) })
  }
  return (
    <div className="space-y-4">
      {canManage && <div className="flex justify-end"><Button onClick={() => setEditing('new')}><Plus /> New working hours</Button></div>}
      {hours.data.length === 0 ? <EmptyState icon={CalendarClock} title="No working hours yet" description="Without a calendar, policies run 24/7." /> : (
        <ul className="grid gap-4 lg:grid-cols-2">
          {hours.data.map((h) => (
            <li key={h.id}>
              <Card className="h-full">
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <CardTitle>{h.name}</CardTitle>
                      <CardDescription>{h.timezone}{h.policies.length > 0 && ` · used by ${h.policies.join(', ')}`}</CardDescription>
                    </div>
                    {canManage && (
                      <div className="flex shrink-0 gap-1">
                        <Button variant="ghost" size="icon" aria-label={`Edit ${h.name}`} onClick={() => setEditing(h)}><Pencil /></Button>
                        <Button variant="ghost" size="icon" aria-label={`Delete ${h.name}`} onClick={() => del(h)}><Trash2 /></Button>
                      </div>
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  <dl className="grid grid-cols-[6rem_1fr] gap-y-0.5 text-sm">
                    {WEEKDAYS.map((d) => <div key={d} className="contents"><dt className="text-muted-foreground">{WEEKDAY_LABEL[d]}</dt><dd>{fmtDay(h.schedule[d]) || <span className="text-muted-foreground">Closed</span>}</dd></div>)}
                  </dl>
                  {h.holidays.length > 0 && <p className="mt-2 text-xs text-muted-foreground">{h.holidays.length} holiday(s): {h.holidays.slice(0, 3).map((x) => x.date).join(', ')}{h.holidays.length > 3 ? '…' : ''}</p>}
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
      {editing && <HoursDialog hours={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

export function SLAPage() {
  return (
    <div className="space-y-5">
      <PageHeader title="SLA" description="Response and resolution targets, the working hours they run on, and how well they're being met." />
      <Tabs defaultValue="report">
        <TabsList>
          <TabsTrigger value="report"><ShieldCheck /> Compliance</TabsTrigger>
          <TabsTrigger value="policies"><Timer /> Policies</TabsTrigger>
          <TabsTrigger value="hours"><CalendarClock /> Working hours</TabsTrigger>
        </TabsList>
        <TabsContent value="report" className="pt-4"><Report /></TabsContent>
        <TabsContent value="policies" className="pt-4"><Policies /></TabsContent>
        <TabsContent value="hours" className="pt-4"><Hours /></TabsContent>
      </Tabs>
    </div>
  )
}
