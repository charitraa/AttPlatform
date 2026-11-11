import { Building2, Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { NativeSelect } from '@/components/forms/native-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { useCan } from '@/stores/auth'
import { useCustomers } from './api'
import { CustomerFormDialog } from './customer-form-dialog'

const PAGE_SIZE = 25

export function CustomersPage() {
  const navigate = useNavigate()
  const canManage = useCan('customers.manage')
  const [search, setSearch] = useState('')
  const [tier, setTier] = useState('')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const customers = useCustomers({ search: useDebouncedValue(search), tier, page })
  const total = customers.data?.count ?? 0

  return (
    <div className="space-y-5">
      <PageHeader title="Customers" description="Accounts you provide service to."
        actions={canManage && <Button onClick={() => setCreating(true)}><Plus /> Add customer</Button>} />
      <div className="flex flex-wrap gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" aria-label="Search customers" placeholder="Name, email, city or contact" className="pl-8"
            value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        </div>
        <NativeSelect aria-label="Tier" className="w-40" value={tier} onChange={(e) => { setTier(e.target.value); setPage(1) }}>
          <option value="">All tiers</option><option value="standard">Standard</option><option value="premium">Premium</option><option value="enterprise">Enterprise</option>
        </NativeSelect>
      </div>
      {customers.isError ? <ErrorState error={customers.error} onRetry={() => customers.refetch()} /> : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Customer</TableHead>
                <TableHead className="hidden md:table-cell">Primary contact</TableHead>
                <TableHead className="hidden sm:table-cell">City</TableHead>
                <TableHead className="text-right">Open tickets</TableHead>
                <TableHead className="hidden text-right lg:table-cell">Assets</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {customers.isPending
                ? Array.from({ length: 6 }, (_, i) => <TableRow key={i}><TableCell colSpan={5}><Skeleton className="h-8" /></TableCell></TableRow>)
                : customers.data.results.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        <Link to={`/customers/${c.id}`} className="font-medium hover:underline">{c.name}</Link>
                        {c.tier !== 'standard' && <Badge variant="secondary" className="ml-2 capitalize">{c.tier}</Badge>}
                      </TableCell>
                      <TableCell className="hidden md:table-cell">{c.primary_contact?.name ?? <span className="text-muted-foreground">—</span>}</TableCell>
                      <TableCell className="hidden sm:table-cell">{c.city || <span className="text-muted-foreground">—</span>}</TableCell>
                      <TableCell className="text-right tabular-nums">{c.open_ticket_count ?? 0}</TableCell>
                      <TableCell className="hidden text-right tabular-nums lg:table-cell">{c.asset_count ?? 0}</TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
          {customers.data?.count === 0 && <EmptyState icon={Building2} className="m-4" title={search || tier ? 'No customers match' : 'No customers yet'} />}
        </div>
      )}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{total} customers · page {page}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={!customers.data?.previous} onClick={() => setPage((p) => p - 1)}>Previous</Button>
            <Button variant="outline" size="sm" disabled={!customers.data?.next} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      )}
      {creating && <CustomerFormDialog open onClose={() => setCreating(false)} onSaved={(c) => navigate(`/customers/${c.id}`)} />}
    </div>
  )
}
