import { ArrowLeft, Pencil, Plus, Star, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState } from '@/components/common/states'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAssets } from '@/features/assets/api'
import { useTickets } from '@/features/tickets/api'
import { PriorityLabel, StatusBadge } from '@/features/tickets/components/badges'
import { formatDate, formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { useCan } from '@/stores/auth'
import { type Contact, useContacts, useCustomer, useDeleteContact, useSaveContact } from './api'
import { CustomerFormDialog } from './customer-form-dialog'

function ContactDialog({ customerId, contact, onClose }: { customerId: string; contact?: Contact; onClose: () => void }) {
  const save = useSaveContact(customerId)
  const [form, setForm] = useState({
    name: contact?.name ?? '', email: contact?.email ?? '', phone: contact?.phone ?? '',
    job_title: contact?.job_title ?? '', is_primary: contact?.is_primary ?? false,
  })
  const [error, setError] = useState<string | null>(null)
  const submit = async () => {
    try {
      await save.mutateAsync({ id: contact?.id, ...form })
      toast.success(contact ? 'Contact updated' : 'Contact added')
      onClose()
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }
  const bind = (k: 'name' | 'email' | 'phone' | 'job_title') => ({ value: form[k], onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value }) })
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{contact ? 'Edit contact' : 'Add contact'}</DialogTitle></DialogHeader>
        <div className="grid gap-4">
          <FormError message={error} />
          <Field label="Name"><Input autoFocus {...bind('name')} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Email"><Input type="email" {...bind('email')} /></Field>
            <Field label="Phone"><Input type="tel" {...bind('phone')} /></Field>
          </div>
          <Field label="Job title"><Input {...bind('job_title')} /></Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-primary" checked={form.is_primary} onChange={(e) => setForm({ ...form, is_primary: e.target.checked })} />
            Primary contact
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={!form.name.trim() || save.isPending}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function CustomerDetailPage() {
  const { id = '' } = useParams()
  const canManage = useCan('customers.manage')
  const canCreateTicket = useCan('tickets.create')
  const customer = useCustomer(id)
  const contacts = useContacts(id)
  const assets = useAssets({ customer: id, page_size: 50 })
  const tickets = useTickets({ customer: id, status: 'new,open,assigned,in_progress,pending_customer,pending_parts,escalated,resolved,closed,reopened' })
  const removeContact = useDeleteContact(id)
  const [editing, setEditing] = useState(false)
  const [contactDialog, setContactDialog] = useState<Contact | 'new' | null>(null)

  if (customer.isPending) return <div className="space-y-4"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-40" /></div>
  if (customer.isError) return <ErrorState error={customer.error} onRetry={() => customer.refetch()} />
  const c = customer.data
  const address = [c.address_line1, c.city, c.country].filter(Boolean).join(', ')

  return (
    <div className="space-y-6">
      <div className="space-y-3 border-b pb-5">
        <Link to="/customers" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Customers</Link>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{c.name}</h1>
            <p className="text-sm text-muted-foreground capitalize">{c.type} · {c.tier} tier{c.archived_at ? ' · archived' : ''}</p>
          </div>
          <div className="flex gap-2">
            {canCreateTicket && <Button size="sm" nativeButton={false} render={<Link to={`/tickets/new?customer=${c.id}`} />}><Plus /> New ticket</Button>}
            {canManage && <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Pencil /> Edit</Button>}
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Account</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div><span className="text-muted-foreground">Email: </span>{c.email || '—'}</div>
              <div><span className="text-muted-foreground">Phone: </span>{c.phone || '—'}</div>
              <div><span className="text-muted-foreground">Address: </span>{address || '—'}</div>
              <div><span className="text-muted-foreground">Customer since: </span>{formatDate(c.created_at)}</div>
              {c.notes && <p className="rounded-md bg-muted p-2 whitespace-pre-wrap">{c.notes}</p>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Contacts</CardTitle>
              {canManage && <Button size="sm" variant="ghost" onClick={() => setContactDialog('new')}><Plus /> Add</Button>}
            </CardHeader>
            <CardContent>
              {contacts.data?.length ? (
                <ul className="divide-y">
                  {contacts.data.map((ct) => (
                    <li key={ct.id} className="flex items-start gap-2 py-2 text-sm">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1 font-medium">{ct.name}{ct.is_primary && <Star className="size-3 fill-current text-warning" aria-label="Primary contact" />}</div>
                        <div className="text-xs text-muted-foreground">{[ct.job_title, ct.email, ct.phone].filter(Boolean).join(' · ') || '—'}</div>
                        {ct.has_portal_access && <Badge variant="outline" className="mt-1">Portal access</Badge>}
                      </div>
                      {canManage && (
                        <div className="flex">
                          <Button size="icon-sm" variant="ghost" aria-label={`Edit ${ct.name}`} onClick={() => setContactDialog(ct)}><Pencil /></Button>
                          <Button size="icon-sm" variant="ghost" aria-label={`Remove ${ct.name}`} onClick={() => removeContact.mutate(ct.id, { onSuccess: () => toast.success('Contact removed') })}><Trash2 /></Button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              ) : <p className="text-sm text-muted-foreground">No contacts yet.</p>}
            </CardContent>
          </Card>
        </div>

        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader><CardTitle>Tickets</CardTitle></CardHeader>
            <CardContent className="p-0">
              {tickets.data?.count ? (
                <Table>
                  <TableHeader><TableRow><TableHead>Ticket</TableHead><TableHead>Status</TableHead><TableHead className="hidden sm:table-cell">Priority</TableHead><TableHead className="hidden md:table-cell">Updated</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {tickets.data.results.map((t) => (
                      <TableRow key={t.id}>
                        <TableCell className="max-w-xs"><Link to={`/tickets/${t.id}`} className="block truncate hover:underline"><span className="font-mono text-xs text-muted-foreground">{t.reference}</span> {t.title}</Link></TableCell>
                        <TableCell><StatusBadge status={t.status} /></TableCell>
                        <TableCell className="hidden sm:table-cell"><PriorityLabel priority={t.priority} /></TableCell>
                        <TableCell className="hidden text-muted-foreground md:table-cell">{formatRelative(t.updated_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : <p className="px-6 pb-4 text-sm text-muted-foreground">{tickets.isPending ? 'Loading…' : 'No tickets for this customer.'}</p>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Assets</CardTitle></CardHeader>
            <CardContent className="p-0">
              {assets.data?.count ? (
                <Table>
                  <TableHeader><TableRow><TableHead>Asset</TableHead><TableHead className="hidden sm:table-cell">Model</TableHead><TableHead>Warranty</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {assets.data.results.map((a) => (
                      <TableRow key={a.id}>
                        <TableCell><span className="font-mono text-xs text-muted-foreground">{a.asset_tag}</span> {a.name}</TableCell>
                        <TableCell className="hidden sm:table-cell">{[a.manufacturer, a.model].filter(Boolean).join(' ') || '—'}</TableCell>
                        <TableCell className={a.under_warranty ? 'text-success' : 'text-muted-foreground'}>{a.warranty_expires_at ? `${a.under_warranty ? 'Until' : 'Ended'} ${formatDate(a.warranty_expires_at)}` : '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : <p className="px-6 pb-4 text-sm text-muted-foreground">{assets.isPending ? 'Loading…' : 'No registered assets.'}</p>}
            </CardContent>
          </Card>
        </div>
      </div>
      {editing && <CustomerFormDialog customer={c} open onClose={() => setEditing(false)} />}
      {contactDialog && <ContactDialog customerId={c.id} contact={contactDialog === 'new' ? undefined : contactDialog} onClose={() => setContactDialog(null)} />}
    </div>
  )
}
