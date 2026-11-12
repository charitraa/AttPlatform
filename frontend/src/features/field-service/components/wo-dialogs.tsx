import { Plus, Star, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { firstErrorMessage } from '@/lib/forms'
import { cn } from '@/lib/utils'
import {
  type WorkOrder, TECH_STATUS_LABEL, useAdvance, useAssignWO, useCancelWO, useConfirmWO, useDecline, useScheduleWO,
  useSuggestions,
} from '../api'

type DialogProps = { wo: WorkOrder; onClose: () => void }

function useSubmit(onClose: () => void) {
  const [error, setError] = useState<string | null>(null)
  const run = async (fn: () => Promise<unknown>, success: string) => {
    setError(null)
    try {
      const res = await fn()
      toast.success(success)
      // e.g. reassigning releases a visit the new technician can't make
      ;(res as { warnings?: string[] } | undefined)?.warnings?.forEach((w) => toast.warning(w))
      onClose()
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }
  return { error, run }
}

// ------------------------------------------------------------------- assign
export function AssignDialog({ wo, onClose }: DialogProps) {
  const suggestions = useSuggestions(wo.id, true)
  const assign = useAssignWO(wo.id)
  const [selected, setSelected] = useState<string>(wo.technician?.id ?? '')
  const { error, run } = useSubmit(onClose)
  const candidates = suggestions.data?.candidates ?? []
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Assign technician</DialogTitle>
          <DialogDescription>Ranked by required skills, availability, current workload and distance to the site.</DialogDescription>
        </DialogHeader>
        <FormError message={error} />
        {suggestions.isPending ? <p className="text-sm text-muted-foreground">Ranking technicians…</p> : (
          <ul role="radiogroup" aria-label="Technician" className="max-h-80 space-y-2 overflow-y-auto">
            {candidates.map((c, i) => {
              const blocked = !!c.blocked_reason
              return (
                <li key={c.technician_id}>
                  <button type="button" role="radio" aria-checked={selected === c.technician_id} disabled={blocked}
                    onClick={() => setSelected(c.technician_id)}
                    className={cn('w-full rounded-lg border p-3 text-left transition-colors hover:bg-muted/50 disabled:cursor-not-allowed disabled:opacity-60',
                      selected === c.technician_id && 'border-primary ring-2 ring-primary/20')}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{c.name}{i === 0 && !blocked && <span className="ml-2 text-xs font-normal text-primary">Best match</span>}</span>
                      <span className="text-xs text-muted-foreground">{blocked ? c.blocked_reason : `score ${c.score.toFixed(2)}`}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                      <span>{TECH_STATUS_LABEL[c.status as keyof typeof TECH_STATUS_LABEL] ?? c.status}</span>
                      <span>{c.active_jobs} active job(s)</span>
                      {c.distance_km !== null && <span>{c.distance_km} km away</span>}
                      {c.matched_skills.length > 0 && <span className="text-success">Has: {c.matched_skills.join(', ')}</span>}
                      {c.missing_skills.length > 0 && <span className="text-warning">Missing: {c.missing_skills.join(', ')}</span>}
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        <DialogFooter>
          {wo.technician && <Button variant="ghost" className="mr-auto" onClick={() => run(() => assign.mutateAsync(null), 'Technician removed')}>Unassign</Button>}
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!selected || selected === wo.technician?.id || assign.isPending}
            onClick={() => run(() => assign.mutateAsync(selected), 'Technician assigned')}>Assign</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------ schedule
const toLocalInput = (iso: string | null | undefined) => {
  if (!iso) return ''
  const d = new Date(iso)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

export function ScheduleDialog({ wo, onClose }: DialogProps) {
  const schedule = useScheduleWO(wo.id)
  const [start, setStart] = useState(toLocalInput(wo.appointment?.starts_at))
  const [hours, setHours] = useState('2')
  const [notes, setNotes] = useState(wo.appointment?.notes ?? '')
  const [error, setError] = useState<string | null>(null)
  const submit = async () => {
    setError(null)
    const s = new Date(start)
    const e = new Date(s.getTime() + Number(hours) * 3600_000)
    try {
      const res = await schedule.mutateAsync({ starts_at: s.toISOString(), ends_at: e.toISOString(), notes })
      toast.success(wo.appointment ? 'Visit rescheduled' : 'Visit scheduled')
      res.warnings?.forEach((w) => toast.warning(w))
      onClose()
    } catch (err) {
      setError(firstErrorMessage(err))
    }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{wo.appointment ? 'Reschedule visit' : 'Schedule visit'}</DialogTitle>
          <DialogDescription>{wo.technician?.name}. Double bookings and time off are blocked automatically.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <FormError message={error} />
          <div className="grid grid-cols-[1fr_7rem] gap-3">
            <Field label="Start"><Input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
            <Field label="Duration (h)"><Input type="number" min={0.5} max={12} step={0.5} value={hours} onChange={(e) => setHours(e.target.value)} /></Field>
          </div>
          <Field label="Notes for the technician"><Input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={!start || !(Number(hours) > 0) || schedule.isPending}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------- reason (decline / cancel)
export function ReasonDialog({ wo, mode, onClose }: DialogProps & { mode: 'decline' | 'cancel' }) {
  const decline = useDecline(wo.id)
  const cancel = useCancelWO(wo.id)
  const [reason, setReason] = useState('')
  const { error, run } = useSubmit(onClose)
  const decl = mode === 'decline'
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{decl ? 'Hand this job back' : `Cancel ${wo.reference}`}</DialogTitle>
          <DialogDescription>{decl ? 'The dispatcher will reassign it. Any scheduled visit is released.' : 'The visit is released and the technician is notified.'}</DialogDescription>
        </DialogHeader>
        <FormError message={error} />
        <Field label="Reason"><Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus /></Field>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Back</Button>
          <Button variant="destructive" disabled={!reason.trim() || decline.isPending || cancel.isPending}
            onClick={() => run(() => (decl ? decline.mutateAsync(reason) : cancel.mutateAsync(reason)), decl ? 'Job handed back' : 'Work order cancelled')}>
            {decl ? 'Hand back' : 'Cancel work order'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------ complete
type Part = { name: string; quantity: string; unit_cost: string }

export function CompleteDialog({ wo, onClose }: DialogProps) {
  const advance = useAdvance(wo.id)
  const [summary, setSummary] = useState(wo.completion_summary)
  const [notes, setNotes] = useState(wo.service_notes)
  const [parts, setParts] = useState<Part[]>([])
  const { error, run } = useSubmit(onClose)
  const setPart = (i: number, patch: Partial<Part>) => setParts(parts.map((p, j) => (j === i ? { ...p, ...patch } : p)))
  const submit = () => run(() => advance.mutateAsync({
    status: 'completed', completion_summary: summary, service_notes: notes,
    parts_used: parts.filter((p) => p.name.trim()).map((p) => ({ name: p.name.trim(), quantity: Number(p.quantity) || 1, unit_cost: p.unit_cost || null })),
  }), 'Job completed')
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Complete job</DialogTitle>
          <DialogDescription>At least one photo or document is required. Time on site is calculated automatically.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <FormError message={error} />
          <Field label="Work carried out"><Textarea rows={4} value={summary} onChange={(e) => setSummary(e.target.value)} autoFocus /></Field>
          <Field label="Service notes (internal)"><Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
          <div className="space-y-2">
            <div className="flex items-center justify-between"><span className="text-sm font-medium">Parts used</span>
              <Button size="xs" variant="ghost" onClick={() => setParts([...parts, { name: '', quantity: '1', unit_cost: '' }])}><Plus /> Add part</Button></div>
            {parts.map((p, i) => (
              <div key={i} className="grid grid-cols-[1fr_4rem_6rem_auto] gap-2">
                <Input aria-label={`Part ${i + 1} name`} placeholder="Part" value={p.name} onChange={(e) => setPart(i, { name: e.target.value })} />
                <Input aria-label={`Part ${i + 1} quantity`} type="number" min={1} value={p.quantity} onChange={(e) => setPart(i, { quantity: e.target.value })} />
                <Input aria-label={`Part ${i + 1} unit cost`} type="number" min={0} step="0.01" placeholder="Unit cost" value={p.unit_cost} onChange={(e) => setPart(i, { unit_cost: e.target.value })} />
                <Button size="icon-sm" variant="ghost" aria-label={`Remove part ${i + 1}`} onClick={() => setParts(parts.filter((_, j) => j !== i))}><Trash2 /></Button>
              </div>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Back</Button>
          <Button onClick={submit} disabled={!summary.trim() || advance.isPending}>Complete job</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------ confirm
export function ConfirmDialog({ wo, onClose }: DialogProps) {
  const confirm = useConfirmWO(wo.id)
  const [name, setName] = useState('')
  const [rating, setRating] = useState<number | null>(null)
  const [comment, setComment] = useState('')
  const { error, run } = useSubmit(onClose)
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Customer sign-off</DialogTitle>
          <DialogDescription>Hand the device to the customer to confirm the work is complete.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <FormError message={error} />
          <p className="rounded-md bg-muted p-3 text-sm whitespace-pre-wrap">{wo.completion_summary}</p>
          <Field label="Name of person signing off"><Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></Field>
          <div role="radiogroup" aria-label="Rating (optional)" className="flex items-center gap-1">
            <span className="mr-2 text-sm">Rating</span>
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} type="button" role="radio" aria-checked={rating === n} aria-label={`${n} star${n > 1 ? 's' : ''}`}
                onClick={() => setRating(rating === n ? null : n)} className="rounded p-1">
                <Star className={cn('size-6', rating !== null && n <= rating ? 'fill-warning text-warning' : 'text-muted-foreground')} />
              </button>
            ))}
          </div>
          <Field label="Comment (optional)"><Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Back</Button>
          <Button disabled={!name.trim() || confirm.isPending} onClick={() => run(() => confirm.mutateAsync({ signed_by: name, rating, comment }), 'Customer confirmation recorded')}>Confirm completion</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
