import { ClipboardList, Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { useCustomers } from '@/features/customers/api'
import { PriorityLabel } from '@/features/tickets/components/badges'
import type { Priority } from '@/features/tickets/constants'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { formatDateTime, formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { useCan } from '@/stores/auth'
import { useCreateWO, useTechnicians, useWorkOrders, WO_STATUS_LABEL, WO_STATUSES } from './api'
import { WOStatusBadge } from './components/wo-parts'

function CreateDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const create = useCreateWO()
  const customers = useCustomers({ page_size: 100, ordering: 'name' })
  const [customer, setCustomer] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = async () => {
    try {
      const wo = await create.mutateAsync({ customer, title, description })
      toast.success(`${wo.reference} created`)
      navigate(`/work-orders/${wo.id}`)
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader><DialogTitle>New work order</DialogTitle></DialogHeader>
        <div className="grid gap-4">
          <FormError message={error} />
          <p className="text-xs text-muted-foreground">For a reported problem, create the work order from the ticket instead so they stay linked.</p>
          <Field label="Customer">
            <NativeSelect value={customer} onChange={(e) => setCustomer(e.target.value)}>
              <option value="">Choose a customer</option>
              {customers.data?.results.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Title"><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Quarterly generator maintenance" /></Field>
          <Field label="Description"><Textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={!customer || !title.trim() || create.isPending}>Create</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function WorkOrdersPage() {
  const canManage = useCan('work_orders.manage')
  const seesAll = useCan('work_orders.view_all')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('active')
  const [technician, setTechnician] = useState('')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const technicians = useTechnicians()
  const orders = useWorkOrders({ search: useDebouncedValue(search), status, technician, page, ordering: 'scheduled_start' })

  return (
    <div className="space-y-5">
      <PageHeader title="Work orders" description="On-site jobs, from dispatch to customer sign-off."
        actions={canManage && <Button onClick={() => setCreating(true)}><Plus /> New work order</Button>} />
      <div className="flex flex-wrap gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" aria-label="Search work orders" placeholder="WO number, title, customer or address" className="pl-8"
            value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        </div>
        <NativeSelect aria-label="Work order status" className="w-40" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="active">Open</option>
          <option value={WO_STATUSES.join(',')}>Any status</option>
          {WO_STATUSES.map((s) => <option key={s} value={s}>{WO_STATUS_LABEL[s]}</option>)}
        </NativeSelect>
        {seesAll && (
          <NativeSelect aria-label="Technician" className="w-48" value={technician} onChange={(e) => { setTechnician(e.target.value); setPage(1) }}>
            <option value="">Any technician</option>
            <option value="none">Unassigned</option>
            {technicians.data?.results.map((t) => <option key={t.id} value={t.id}>{t.user.full_name}</option>)}
          </NativeSelect>
        )}
      </div>
      {orders.isError ? <ErrorState error={orders.error} onRetry={() => orders.refetch()} /> : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Work order</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Customer</TableHead>
                <TableHead className="hidden lg:table-cell">Technician</TableHead>
                <TableHead className="hidden sm:table-cell">Visit</TableHead>
                <TableHead className="hidden xl:table-cell">Priority</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.isPending
                ? Array.from({ length: 6 }, (_, i) => <TableRow key={i}><TableCell colSpan={6}><Skeleton className="h-9" /></TableCell></TableRow>)
                : orders.data.results.map((w) => (
                    <TableRow key={w.id}>
                      <TableCell className="max-w-[22rem]">
                        <Link to={`/work-orders/${w.id}`} className="group block min-w-0">
                          <span className="font-mono text-xs text-muted-foreground">{w.reference}{w.ticket && ` · ${w.ticket.reference}`}</span>
                          <span className="block truncate font-medium group-hover:underline">{w.title}</span>
                        </Link>
                      </TableCell>
                      <TableCell><WOStatusBadge status={w.status} /></TableCell>
                      <TableCell className="hidden max-w-[12rem] truncate md:table-cell">{w.customer.name}</TableCell>
                      <TableCell className="hidden lg:table-cell">{w.technician?.name ?? <span className="text-muted-foreground">Unassigned</span>}</TableCell>
                      <TableCell className="hidden sm:table-cell" title={formatDateTime(w.scheduled_start)}>
                        {w.scheduled_start ? formatRelative(w.scheduled_start) : <span className="text-muted-foreground">Not scheduled</span>}
                      </TableCell>
                      <TableCell className="hidden xl:table-cell"><PriorityLabel priority={w.priority as Priority} /></TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
          {orders.data?.count === 0 && <EmptyState icon={ClipboardList} className="m-4" title="No work orders match" />}
        </div>
      )}
      {orders.data && orders.data.count > 25 && (
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" disabled={!orders.data.previous} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <Button variant="outline" size="sm" disabled={!orders.data.next} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}
      {creating && <CreateDialog onClose={() => setCreating(false)} />}
    </div>
  )
}
