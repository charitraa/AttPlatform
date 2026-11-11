import { Archive, ArchiveRestore, ChevronDown, Pencil, Siren, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useMembers } from '@/features/users/api'
import { ApiError } from '@/lib/api/client'
import { type Ticket, useArchive, useAssign, useCategories, useEscalate, useTransition, useUpdateTicket } from '../api'
import { PRIORITIES, PRIORITY_LABEL, STATUS_LABEL, TRANSITION_LABEL, type TicketStatus } from '../constants'

const message = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')
const fieldError = (e: unknown, field: string): string | undefined => {
  if (!(e instanceof ApiError) || !e.details || typeof e.details !== 'object') return undefined
  const v = (e.details as Record<string, unknown>)[field]
  return Array.isArray(v) ? String(v[0]) : undefined
}

// ------------------------------------------------------------------ status change
function TransitionDialog({ ticket, target, onClose }: { ticket: Ticket; target: TicketStatus | null; onClose: () => void }) {
  const transition = useTransition(ticket.id)
  const [note, setNote] = useState('')
  const [resolution, setResolution] = useState(ticket.resolution_notes)
  const [error, setError] = useState<unknown>(null)
  const resolving = target === 'resolved'
  const isStaffNote = ticket.capabilities.internal_notes

  const submit = async () => {
    if (!target) return
    setError(null)
    try {
      await transition.mutateAsync({ status: target, note, ...(resolving && { resolution_notes: resolution }) })
      toast.success(`${ticket.reference} is now ${STATUS_LABEL[target].toLowerCase()}`)
      onClose()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <Dialog open={!!target} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{target ? TRANSITION_LABEL[target] : ''}</DialogTitle>
          <DialogDescription>
            {STATUS_LABEL[ticket.status]} → {target ? STATUS_LABEL[target] : ''}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <FormError message={error && !fieldError(error, 'resolution_notes') ? message(error) : null} />
          {resolving && (
            <Field label="Resolution notes" error={fieldError(error, 'resolution_notes')}
              description="What fixed the issue? This is shared with the customer and future agents.">
              <Textarea rows={4} value={resolution} onChange={(e) => setResolution(e.target.value)} autoFocus />
            </Field>
          )}
          <Field label={isStaffNote ? 'Internal note (optional)' : 'Comment (optional)'}
            description={isStaffNote ? 'Visible to staff only.' : undefined}>
            <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} autoFocus={!resolving} />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={transition.isPending}>{transition.isPending ? 'Saving…' : 'Confirm'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ----------------------------------------------------------------------- assign
const AGENT_ROLES = new Set(['support_agent', 'ops_manager', 'org_admin', 'super_admin'])

function AssignDialog({ ticket, open, onClose }: { ticket: Ticket; open: boolean; onClose: () => void }) {
  const members = useMembers({ is_active: 'true', page_size: 100 })
  const assign = useAssign(ticket.id)
  const [agent, setAgent] = useState(ticket.assigned_agent?.id ?? '')
  const [tech, setTech] = useState(ticket.assigned_technician?.id ?? '')
  const [error, setError] = useState<unknown>(null)
  const people = members.data?.results ?? []

  const submit = async () => {
    setError(null)
    try {
      await assign.mutateAsync({ agent: agent || null, technician: tech || null })
      toast.success('Assignment updated')
      onClose()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Assign {ticket.reference}</DialogTitle>
          <DialogDescription>Assigning an agent to a new ticket moves it to Assigned.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <FormError message={error && !fieldError(error, 'agent') && !fieldError(error, 'technician') ? message(error) : null} />
          <Field label="Agent" error={fieldError(error, 'agent')}>
            <NativeSelect value={agent} onChange={(e) => setAgent(e.target.value)} disabled={members.isPending}>
              <option value="">Unassigned</option>
              {people.filter((m) => AGENT_ROLES.has(m.role.code)).map((m) => (
                <option key={m.id} value={m.id}>{m.user.full_name} · {m.role.name}</option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Field technician" error={fieldError(error, 'technician')}>
            <NativeSelect value={tech} onChange={(e) => setTech(e.target.value)} disabled={members.isPending}>
              <option value="">None</option>
              {people.filter((m) => m.role.code === 'field_technician').map((m) => (
                <option key={m.id} value={m.id}>{m.user.full_name}</option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={assign.isPending}>{assign.isPending ? 'Saving…' : 'Save assignment'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------- escalate
function EscalateDialog({ ticket, open, onClose }: { ticket: Ticket; open: boolean; onClose: () => void }) {
  const escalate = useEscalate(ticket.id)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<unknown>(null)
  const submit = async () => {
    setError(null)
    try {
      await escalate.mutateAsync(reason)
      toast.success(`${ticket.reference} escalated`)
      onClose()
    } catch (e) {
      setError(e)
    }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Escalate {ticket.reference}</DialogTitle>
          <DialogDescription>The reason is recorded as an internal note.</DialogDescription>
        </DialogHeader>
        <Field label="Reason" error={fieldError(error, 'reason') ?? (error ? message(error) : undefined)}>
          <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
        </Field>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button variant="destructive" onClick={submit} disabled={escalate.isPending || !reason.trim()}>Escalate</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// -------------------------------------------------------------------------- edit
function EditDialog({ ticket, open, onClose }: { ticket: Ticket; open: boolean; onClose: () => void }) {
  const update = useUpdateTicket(ticket.id)
  const categories = useCategories()
  const [title, setTitle] = useState(ticket.title)
  const [description, setDescription] = useState(ticket.description)
  const [priority, setPriority] = useState<string>(ticket.priority)
  const [category, setCategory] = useState(ticket.category?.id ?? '')
  const [tags, setTags] = useState(ticket.tags.join(', '))
  const [error, setError] = useState<unknown>(null)

  const submit = async () => {
    setError(null)
    try {
      await update.mutateAsync({
        title, description, priority, category: category || null,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
      })
      toast.success('Ticket updated')
      onClose()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader><DialogTitle>Edit {ticket.reference}</DialogTitle></DialogHeader>
        <div className="grid gap-4">
          <FormError message={error && !fieldError(error, 'title') ? message(error) : null} />
          <Field label="Title" error={fieldError(error, 'title')}><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Description"><Textarea rows={6} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Priority">
              <NativeSelect value={priority} onChange={(e) => setPriority(e.target.value)}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
              </NativeSelect>
            </Field>
            <Field label="Category">
              <NativeSelect value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">Uncategorised</option>
                {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}
              </NativeSelect>
            </Field>
          </div>
          <Field label="Tags" description="Comma-separated"><Input value={tags} onChange={(e) => setTags(e.target.value)} /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={update.isPending || !title.trim()}>{update.isPending ? 'Saving…' : 'Save changes'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------ action bar
export function TicketActions({ ticket }: { ticket: Ticket }) {
  const [target, setTarget] = useState<TicketStatus | null>(null)
  const [dialog, setDialog] = useState<'assign' | 'escalate' | 'edit' | 'archive' | null>(null)
  const archive = useArchive(ticket.id)
  const transitions = ticket.allowed_transitions.filter((s) => s !== 'escalated')
  const canEscalate = ticket.allowed_transitions.includes('escalated') && ticket.capabilities.edit
  const caps = ticket.capabilities
  // The customer-facing confirm action gets plain wording.
  const label = (s: TicketStatus) => (!caps.internal_notes && s === 'closed' ? 'Confirm resolution' : TRANSITION_LABEL[s])

  const toggleArchive = async () => {
    try {
      await archive.mutateAsync(!ticket.archived_at)
      toast.success(ticket.archived_at ? 'Ticket restored' : 'Ticket archived')
    } catch (e) {
      toast.error(message(e))
    } finally {
      setDialog(null)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {transitions.length === 1 && (
        <Button size="sm" onClick={() => setTarget(transitions[0])}>{label(transitions[0])}</Button>
      )}
      {transitions.length > 1 && (
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button size="sm" />}>Change status <ChevronDown /></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {transitions.map((s) => <DropdownMenuItem key={s} onClick={() => setTarget(s)}>{label(s)}</DropdownMenuItem>)}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {caps.assign && <Button size="sm" variant="outline" onClick={() => setDialog('assign')}><UserPlus /> Assign</Button>}
      {canEscalate && <Button size="sm" variant="outline" onClick={() => setDialog('escalate')}><Siren /> Escalate</Button>}
      {caps.edit && <Button size="sm" variant="outline" onClick={() => setDialog('edit')}><Pencil /> Edit</Button>}
      {caps.archive && (
        <Button size="sm" variant="ghost" onClick={() => setDialog('archive')}>
          {ticket.archived_at ? <><ArchiveRestore /> Unarchive</> : <><Archive /> Archive</>}
        </Button>
      )}

      <TransitionDialog key={target ?? 'none'} ticket={ticket} target={target} onClose={() => setTarget(null)} />
      {dialog === 'assign' && <AssignDialog ticket={ticket} open onClose={() => setDialog(null)} />}
      {dialog === 'escalate' && <EscalateDialog ticket={ticket} open onClose={() => setDialog(null)} />}
      {dialog === 'edit' && <EditDialog ticket={ticket} open onClose={() => setDialog(null)} />}
      <AlertDialog open={dialog === 'archive'} onOpenChange={(o) => { if (!o) setDialog(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{ticket.archived_at ? 'Unarchive' : 'Archive'} {ticket.reference}?</AlertDialogTitle>
            <AlertDialogDescription>
              {ticket.archived_at
                ? 'The ticket returns to the ticket list and can be worked on again.'
                : 'Archived tickets are hidden from lists and can no longer be edited. Nothing is deleted; you can unarchive it later.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={toggleArchive} disabled={archive.isPending}>{ticket.archived_at ? 'Unarchive' : 'Archive'}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
