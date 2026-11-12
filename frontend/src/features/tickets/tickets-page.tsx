import { ArrowDown, ArrowUp, ArrowUpDown, Plus, Search, Ticket as TicketIcon, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { formatDateTime, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useCan } from '@/stores/auth'
import { SLAChip } from '@/features/sla/components/sla-status'
import { type TicketFilters, useTickets } from './api'
import { PriorityLabel, StatusBadge } from './components/badges'
import { PRIORITIES, PRIORITY_LABEL, STATUSES, STATUS_LABEL } from './constants'

const PAGE_SIZE = 25
const FILTER_KEYS = ['search', 'status', 'priority', 'assigned_agent', 'overdue', 'archived', 'ordering', 'page'] as const

/** Filters live in the URL so views are shareable and survive reloads. */
function useTicketFilters() {
  const [params, setParams] = useSearchParams()
  const filters: TicketFilters = {}
  for (const key of FILTER_KEYS) {
    const value = params.get(key)
    if (value) (filters as Record<string, string | number>)[key] = key === 'page' ? Number(value) : value
  }
  filters.status ??= 'active'
  const set = (patch: Partial<Record<(typeof FILTER_KEYS)[number], string>>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!('page' in patch)) next.delete('page') // any filter change returns to page 1
    setParams(next, { replace: true })
  }
  return { filters, set, hasCustom: FILTER_KEYS.some((k) => k !== 'page' && params.has(k)) }
}

function SortHeader({ field, label, ordering, onSort, className }: {
  field: string; label: string; ordering?: string; onSort: (o: string) => void; className?: string
}) {
  const active = ordering?.replace('-', '') === field
  const desc = ordering?.startsWith('-')
  const Icon = !active ? ArrowUpDown : desc ? ArrowDown : ArrowUp
  return (
    <TableHead className={className} aria-sort={active ? (desc ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => onSort(active && desc ? field : `-${field}`)}>
        {label} <Icon className={cn('size-3.5', !active && 'opacity-40')} aria-hidden />
      </button>
    </TableHead>
  )
}

export function TicketsPage() {
  const navigate = useNavigate()
  const canCreate = useCan('tickets.create')
  const { filters, set, hasCustom } = useTicketFilters()
  const [search, setSearch] = useState(filters.search ?? '')
  const debounced = useDebouncedValue(search)
  useEffect(() => {
    if ((filters.search ?? '') !== debounced) set({ search: debounced })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to the debounced text
  }, [debounced])
  // Keep the box in sync when the URL changes from outside (e.g. global search).
  useEffect(() => setSearch(filters.search ?? ''), [filters.search])

  const tickets = useTickets(filters)
  const page = filters.page ?? 1
  const totalPages = tickets.data ? Math.max(1, Math.ceil(tickets.data.count / PAGE_SIZE)) : 1
  const ordering = filters.ordering ?? '-created_at'

  return (
    <div className="space-y-5">
      <PageHeader
        title="Tickets"
        description={tickets.data ? `${tickets.data.count} ticket${tickets.data.count === 1 ? '' : 's'} match these filters` : 'Service requests and incidents.'}
        actions={canCreate && <Button onClick={() => navigate('/tickets/new')}><Plus /> New ticket</Button>}
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" aria-label="Search tickets" placeholder="Search text or TCK number" className="pl-8"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <NativeSelect aria-label="Status" className="w-44" value={filters.status} onChange={(e) => set({ status: e.target.value === 'active' ? '' : e.target.value })}>
          <option value="active">All active</option>
          <option value={STATUSES.join(',')}>Any status</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="Priority" className="w-36" value={filters.priority ?? ''} onChange={(e) => set({ priority: e.target.value })}>
          <option value="">Any priority</option>
          <option value="high,critical">High + critical</option>
          {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="Assignee" className="w-40" value={filters.assigned_agent ?? ''} onChange={(e) => set({ assigned_agent: e.target.value })}>
          <option value="">Anyone</option>
          <option value="me">Assigned to me</option>
          <option value="none">Unassigned</option>
        </NativeSelect>
        <NativeSelect aria-label="Due" className="w-36" value={filters.overdue ?? ''} onChange={(e) => set({ overdue: e.target.value })}>
          <option value="">Any due date</option>
          <option value="true">Overdue</option>
        </NativeSelect>
        {hasCustom && (
          <Button variant="ghost" size="sm" onClick={() => { setSearch(''); navigate('/tickets', { replace: true }) }}>
            <X /> Clear filters
          </Button>
        )}
      </div>

      {tickets.isError ? (
        <ErrorState error={tickets.error} onRetry={() => tickets.refetch()} />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <SortHeader field="number" label="Ticket" ordering={ordering} onSort={(o) => set({ ordering: o })} />
                <TableHead className="hidden md:table-cell">Customer</TableHead>
                <TableHead>Status</TableHead>
                <SortHeader field="priority" label="Priority" ordering={ordering} onSort={(o) => set({ ordering: o })} />
                <TableHead className="hidden lg:table-cell">Assignee</TableHead>
                <SortHeader field="due_at" label="Due" ordering={ordering} onSort={(o) => set({ ordering: o })} className="hidden xl:table-cell" />
                <SortHeader field="created_at" label="Created" ordering={ordering} onSort={(o) => set({ ordering: o })} className="hidden sm:table-cell" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tickets.isPending
                ? Array.from({ length: 8 }, (_, i) => <TableRow key={i}><TableCell colSpan={7}><Skeleton className="h-9" /></TableCell></TableRow>)
                : tickets.data.results.map((t) => (
                    <TableRow key={t.id} className={cn(tickets.isPlaceholderData && 'opacity-60')}>
                      <TableCell className="max-w-[22rem]">
                        <Link to={`/tickets/${t.id}`} className="group block min-w-0">
                          <span className="font-mono text-xs text-muted-foreground">{t.reference}</span>
                          <span className="block truncate font-medium group-hover:underline">{t.title}</span>
                        </Link>
                      </TableCell>
                      <TableCell className="hidden max-w-[12rem] truncate md:table-cell">{t.customer.name}</TableCell>
                      <TableCell><StatusBadge status={t.status} /></TableCell>
                      <TableCell><PriorityLabel priority={t.priority} /></TableCell>
                      <TableCell className="hidden lg:table-cell">{t.assigned_agent?.full_name ?? <span className="text-muted-foreground">Unassigned</span>}</TableCell>
                      <TableCell className="hidden xl:table-cell">
                        {t.sla ? <SLAChip sla={t.sla} /> : t.due_at ? (
                          <span className={cn(t.is_overdue && 'font-medium text-destructive')} title={formatDateTime(t.due_at)}>
                            {t.is_overdue ? 'Overdue · ' : ''}{formatRelative(t.due_at)}
                          </span>
                        ) : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="hidden text-muted-foreground sm:table-cell" title={formatDateTime(t.created_at)}>{formatRelative(t.created_at)}</TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
          {tickets.data?.count === 0 && (
            <EmptyState icon={TicketIcon} className="m-4" title="No tickets match these filters"
              description={hasCustom ? 'Try clearing a filter.' : canCreate ? 'Create the first ticket to get started.' : undefined}
              action={canCreate && !hasCustom ? <Button size="sm" nativeButton={false} render={<Link to="/tickets/new" />}><Plus /> New ticket</Button> : undefined} />
          )}
        </div>
      )}

      {tickets.data && tickets.data.count > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>Page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={!tickets.data.previous} onClick={() => set({ page: String(page - 1) })}>Previous</Button>
            <Button variant="outline" size="sm" disabled={!tickets.data.next} onClick={() => set({ page: String(page + 1) })}>Next</Button>
          </div>
        </div>
      )}
    </div>
  )
}
