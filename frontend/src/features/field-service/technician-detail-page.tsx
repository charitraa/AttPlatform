import { ArrowLeft, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState } from '@/components/common/states'
import { StatusDot } from '@/components/common/status-indicator'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDate, formatDateTime } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { useAuthStore, useCan } from '@/stores/auth'
import {
  type Technician, TECH_STATUS_LABEL, useAreas, useAvailability, useCerts, useSkills, useTechMutation, useTechnician,
  useWorkOrders,
} from './api'
import { WOStatusBadge } from './components/wo-parts'
import { TECH_HEALTH } from './utils'

function ProfileDialog({ tech, onClose }: { tech: Technician; onClose: () => void }) {
  const { update } = useTechMutation()
  const areas = useAreas()
  const [form, setForm] = useState({
    employee_id: tech.employee_id, status: tech.status, max_daily_jobs: String(tech.max_daily_jobs),
    hourly_cost: tech.hourly_cost ?? '', currency: tech.currency, home_lat: tech.home_lat ?? '', home_lng: tech.home_lng ?? '',
    notes: tech.notes, service_areas: tech.service_areas,
  })
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value })
  const submit = async () => {
    try {
      await update.mutateAsync({
        id: tech.id, ...form, max_daily_jobs: Number(form.max_daily_jobs),
        hourly_cost: form.hourly_cost || null, home_lat: form.home_lat || null, home_lng: form.home_lng || null,
      })
      toast.success('Profile updated')
      onClose()
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Edit {tech.user.full_name}</DialogTitle></DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2"><FormError message={error} /></div>
          <Field label="Employee ID"><Input value={form.employee_id} onChange={set('employee_id')} /></Field>
          <Field label="Status">
            <NativeSelect value={form.status} onChange={set('status')}>{Object.entries(TECH_STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</NativeSelect>
          </Field>
          <Field label="Max visits per day"><Input type="number" min={1} max={30} value={form.max_daily_jobs} onChange={set('max_daily_jobs')} /></Field>
          <div className="grid grid-cols-[1fr_5rem] gap-2">
            <Field label="Hourly cost"><Input type="number" min={0} step="0.01" value={form.hourly_cost} onChange={set('hourly_cost')} /></Field>
            <Field label="Currency"><Input maxLength={3} value={form.currency} onChange={set('currency')} /></Field>
          </div>
          <Field label="Home base latitude" description="Used to estimate travel distance."><Input value={form.home_lat} onChange={set('home_lat')} inputMode="decimal" /></Field>
          <Field label="Home base longitude"><Input value={form.home_lng} onChange={set('home_lng')} inputMode="decimal" /></Field>
          <fieldset className="sm:col-span-2">
            <legend className="mb-1.5 text-sm font-medium">Service areas</legend>
            <div className="flex flex-wrap gap-3">
              {areas.data?.map((a) => (
                <label key={a.id} className="flex items-center gap-1.5 text-sm">
                  <input type="checkbox" className="accent-primary" checked={form.service_areas.includes(a.id)}
                    onChange={(e) => setForm({ ...form, service_areas: e.target.checked ? [...form.service_areas, a.id] : form.service_areas.filter((x) => x !== a.id) })} />
                  {a.name}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={update.isPending}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SkillsCard({ tech, canManage }: { tech: Technician; canManage: boolean }) {
  const skills = useSkills()
  const { setSkills } = useTechMutation()
  const [editing, setEditing] = useState(false)
  const [rows, setRows] = useState(tech.skills.map((s) => ({ skill: s.skill, level: s.level })))
  const save = async () => {
    try {
      await setSkills.mutateAsync({ id: tech.id, skills: rows.filter((r) => r.skill) })
      toast.success('Skills updated')
      setEditing(false)
    } catch (e) {
      toast.error(firstErrorMessage(e))
    }
  }
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Skills</CardTitle>
        {canManage && !editing && <Button size="sm" variant="ghost" onClick={() => { setRows(tech.skills.map((s) => ({ skill: s.skill, level: s.level }))); setEditing(true) }}>Edit</Button>}
      </CardHeader>
      <CardContent>
        {!editing ? (
          tech.skills.length ? (
            <ul className="space-y-2">
              {tech.skills.map((s) => (
                <li key={s.skill} className="flex items-center justify-between gap-2 text-sm">
                  <span>{s.name}</span>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground" aria-label={`Level ${s.level} of 5`}>
                    <span className="flex gap-0.5" aria-hidden>{[1, 2, 3, 4, 5].map((n) => <span key={n} className={`h-1.5 w-4 rounded-full ${n <= s.level ? 'bg-series-1' : 'bg-muted'}`} />)}</span>
                    {s.level}/5
                  </span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted-foreground">No skills recorded. Skills are matched to ticket categories when ranking technicians.</p>
        ) : (
          <div className="space-y-2">
            {rows.map((r, i) => (
              <div key={i} className="grid grid-cols-[1fr_5rem_auto] gap-2">
                <NativeSelect aria-label={`Skill ${i + 1}`} value={r.skill} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, skill: e.target.value } : x)))}>
                  <option value="">Choose…</option>
                  {skills.data?.map((s) => <option key={s.id} value={s.id} disabled={rows.some((x, j) => j !== i && x.skill === s.id)}>{s.name}</option>)}
                </NativeSelect>
                <NativeSelect aria-label={`Skill ${i + 1} level`} value={String(r.level)} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, level: Number(e.target.value) } : x)))}>
                  {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                </NativeSelect>
                <Button size="icon-sm" variant="ghost" aria-label={`Remove skill ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 /></Button>
              </div>
            ))}
            <div className="flex justify-between pt-1">
              <Button size="sm" variant="ghost" onClick={() => setRows([...rows, { skill: '', level: 3 }])}><Plus /> Add skill</Button>
              <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setEditing(false)}>Cancel</Button><Button size="sm" onClick={save} disabled={setSkills.isPending}>Save</Button></div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function CertificationsCard({ tech, canManage }: { tech: Technician; canManage: boolean }) {
  const certs = useCerts(tech.id)
  const { addCert, removeCert } = useTechMutation()
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', issuer: '', expires_at: '' })
  const add = async () => {
    try {
      await addCert.mutateAsync({ id: tech.id, name: form.name, issuer: form.issuer, expires_at: form.expires_at || null })
      setForm({ name: '', issuer: '', expires_at: '' })
      setAdding(false)
    } catch (e) {
      toast.error(firstErrorMessage(e))
    }
  }
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Certifications</CardTitle>
        {canManage && <Button size="sm" variant="ghost" onClick={() => setAdding((v) => !v)}><Plus /> Add</Button>}
      </CardHeader>
      <CardContent className="space-y-3">
        {adding && (
          <div className="grid gap-2 rounded-lg border p-3">
            <Input aria-label="Certification name" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <Input aria-label="Issuer" placeholder="Issuer" value={form.issuer} onChange={(e) => setForm({ ...form, issuer: e.target.value })} />
            <Field label="Expires"><Input type="date" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} /></Field>
            <Button size="sm" onClick={add} disabled={!form.name.trim() || addCert.isPending}>Save certification</Button>
          </div>
        )}
        {certs.data?.length ? (
          <ul className="space-y-2">
            {certs.data.map((c) => (
              <li key={c.id} className="flex items-start justify-between gap-2 text-sm">
                <div>
                  <div className="font-medium">{c.name}</div>
                  <div className="text-xs text-muted-foreground">{[c.issuer, c.expires_at && `expires ${formatDate(c.expires_at)}`].filter(Boolean).join(' · ')}</div>
                </div>
                <div className="flex items-center gap-1">
                  {c.is_expired && <Badge variant="outline" className="border-destructive/50 text-destructive">Expired</Badge>}
                  {canManage && <Button size="icon-sm" variant="ghost" aria-label={`Remove ${c.name}`} onClick={() => removeCert.mutate({ id: tech.id, certId: c.id })}><Trash2 /></Button>}
                </div>
              </li>
            ))}
          </ul>
        ) : !adding && <p className="text-sm text-muted-foreground">None recorded.</p>}
      </CardContent>
    </Card>
  )
}

function AvailabilityCard({ tech, canEdit }: { tech: Technician; canEdit: boolean }) {
  const availability = useAvailability(tech.id)
  const { addAvailability, removeAvailability } = useTechMutation()
  const [form, setForm] = useState({ type: 'time_off', starts_at: '', ends_at: '', note: '' })
  const [error, setError] = useState<string | null>(null)
  const add = async () => {
    setError(null)
    try {
      await addAvailability.mutateAsync({ id: tech.id, ...form, starts_at: new Date(form.starts_at).toISOString(), ends_at: new Date(form.ends_at).toISOString() })
      setForm({ type: 'time_off', starts_at: '', ends_at: '', note: '' })
      toast.success(form.type === 'time_off' ? 'Time off added' : 'Shift added')
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }
  const upcoming = (availability.data ?? []).filter((a) => a.type === 'time_off' || new Date(a.starts_at).getTime() - Date.now() < 7 * 86400_000)
  return (
    <Card>
      <CardHeader><CardTitle>Availability</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {canEdit && (
          <div className="grid gap-2 rounded-lg border p-3 sm:grid-cols-2">
            <div className="sm:col-span-2"><FormError message={error} /></div>
            <Field label="Type"><NativeSelect value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}><option value="time_off">Time off</option><option value="shift">Shift</option></NativeSelect></Field>
            <Field label="Note"><Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
            <Field label="From"><Input type="datetime-local" value={form.starts_at} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} /></Field>
            <Field label="Until"><Input type="datetime-local" value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} /></Field>
            <div className="sm:col-span-2"><Button size="sm" onClick={add} disabled={!form.starts_at || !form.ends_at || addAvailability.isPending}>Add</Button></div>
          </div>
        )}
        {upcoming.length ? (
          <ul className="max-h-64 space-y-1.5 overflow-y-auto">
            {upcoming.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2 text-sm">
                <span>
                  <Badge variant="outline" className={a.type === 'time_off' ? 'border-warning/50 text-warning' : ''}>{a.type === 'time_off' ? 'Time off' : 'Shift'}</Badge>{' '}
                  {formatDateTime(a.starts_at)} – {new Date(a.ends_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                  {a.note && <span className="text-muted-foreground"> · {a.note}</span>}
                </span>
                {canEdit && <Button size="icon-sm" variant="ghost" aria-label="Remove entry" onClick={() => removeAvailability.mutate({ id: tech.id, entryId: a.id })}><Trash2 /></Button>}
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-muted-foreground">No upcoming shifts or time off.</p>}
      </CardContent>
    </Card>
  )
}

export function TechnicianDetailPage() {
  const { id = '' } = useParams()
  const tech = useTechnician(id)
  const canManage = useCan('technicians.manage')
  const meId = useAuthStore((s) => s.user?.id)
  const jobs = useWorkOrders({ technician: id, status: 'active' }, !!id)
  const [editing, setEditing] = useState(false)
  if (tech.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-48" /></div>
  if (tech.isError) return <ErrorState error={tech.error} onRetry={() => tech.refetch()} />
  const t = tech.data
  const isSelf = t.user.id === meId

  return (
    <div className="space-y-6">
      <div className="space-y-3 border-b pb-5">
        <Link to="/technicians" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Technicians</Link>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{t.user.full_name}</h1>
            <p className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground"><StatusDot health={TECH_HEALTH[t.status]} /> {TECH_STATUS_LABEL[t.status]} · {t.user.email}{t.user.phone && ` · ${t.user.phone}`}</p>
          </div>
          {canManage && <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit profile</Button>}
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader><CardTitle>Open jobs</CardTitle></CardHeader>
            <CardContent className="p-0">
              {jobs.data?.count ? (
                <Table>
                  <TableHeader><TableRow><TableHead>Work order</TableHead><TableHead>Status</TableHead><TableHead className="hidden sm:table-cell">Visit</TableHead></TableRow></TableHeader>
                  <TableBody>{jobs.data.results.map((w) => (
                    <TableRow key={w.id}>
                      <TableCell><Link to={`/work-orders/${w.id}`} className="hover:underline"><span className="font-mono text-xs text-muted-foreground">{w.reference}</span> {w.title}</Link><span className="block text-xs text-muted-foreground">{w.customer.name}</span></TableCell>
                      <TableCell><WOStatusBadge status={w.status} /></TableCell>
                      <TableCell className="hidden sm:table-cell">{w.scheduled_start ? formatDateTime(w.scheduled_start) : '—'}</TableCell>
                    </TableRow>
                  ))}</TableBody>
                </Table>
              ) : <p className="px-6 pb-4 text-sm text-muted-foreground">{jobs.isPending ? 'Loading…' : 'No open jobs.'}</p>}
            </CardContent>
          </Card>
          <AvailabilityCard tech={t} canEdit={canManage || isSelf} />
        </div>
        <aside className="space-y-6">
          <SkillsCard key={t.skills.map((s) => s.skill + s.level).join()} tech={t} canManage={canManage} />
          <CertificationsCard tech={t} canManage={canManage} />
          <Card>
            <CardHeader><CardTitle>Profile</CardTitle></CardHeader>
            <CardContent>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Employee ID</dt><dd>{t.employee_id || '—'}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Max visits / day</dt><dd>{t.max_daily_jobs}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Hourly cost</dt><dd>{t.hourly_cost ? `${t.currency} ${t.hourly_cost}` : '—'}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Location sharing</dt><dd>{t.location_sharing_enabled ? 'On (during jobs only)' : 'Off'}</dd></div>
              </dl>
            </CardContent>
          </Card>
        </aside>
      </div>
      {editing && <ProfileDialog tech={t} onClose={() => setEditing(false)} />}
    </div>
  )
}
