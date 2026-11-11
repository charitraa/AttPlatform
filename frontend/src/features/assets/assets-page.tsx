import { Boxes, Pencil, Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useCustomers } from '@/features/customers/api'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { formatDate } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { useCan } from '@/stores/auth'
import { type Asset, type AssetInput, useAssetCategories, useAssets, useSaveAsset } from './api'

const STATUS_LABEL = { active: 'Active', in_repair: 'In repair', retired: 'Retired' } as const

function AssetDialog({ asset, onClose }: { asset?: Asset; onClose: () => void }) {
  const save = useSaveAsset(asset?.id)
  const customers = useCustomers({ page_size: 100, ordering: 'name' })
  const categories = useAssetCategories()
  const [form, setForm] = useState<Record<string, string>>({
    asset_tag: asset?.asset_tag ?? '', name: asset?.name ?? '', customer: asset?.customer ?? '',
    category: asset?.category ?? '', manufacturer: asset?.manufacturer ?? '', model: asset?.model ?? '',
    serial_number: asset?.serial_number ?? '', location: asset?.location ?? '', installed_at: asset?.installed_at ?? '',
    warranty_expires_at: asset?.warranty_expires_at ?? '', status: asset?.status ?? 'active',
  })
  const [error, setError] = useState<string | null>(null)
  const bind = (k: string) => ({ value: form[k], onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value }) })

  const submit = async () => {
    setError(null)
    // Empty optional fields go to the API as null, not "".
    const payload = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, v === '' && ['category', 'installed_at', 'warranty_expires_at'].includes(k) ? null : v]),
    ) as AssetInput
    try {
      await save.mutateAsync(payload)
      toast.success(asset ? 'Asset updated' : 'Asset registered')
      onClose()
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader><DialogTitle>{asset ? `Edit ${asset.asset_tag}` : 'Register asset'}</DialogTitle></DialogHeader>
        <div className="grid gap-4">
          <FormError message={error} />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Asset tag"><Input autoFocus {...bind('asset_tag')} /></Field>
            <Field label="Name"><Input {...bind('name')} /></Field>
            <Field label="Customer">
              <NativeSelect {...bind('customer')}>
                <option value="">Choose a customer</option>
                {customers.data?.results.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </NativeSelect>
            </Field>
            <Field label="Category">
              <NativeSelect {...bind('category')}>
                <option value="">None</option>
                {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </NativeSelect>
            </Field>
            <Field label="Manufacturer"><Input {...bind('manufacturer')} /></Field>
            <Field label="Model"><Input {...bind('model')} /></Field>
            <Field label="Serial number"><Input {...bind('serial_number')} /></Field>
            <Field label="Location"><Input {...bind('location')} /></Field>
            <Field label="Installed on"><Input type="date" {...bind('installed_at')} /></Field>
            <Field label="Warranty until"><Input type="date" {...bind('warranty_expires_at')} /></Field>
            <Field label="Status">
              <NativeSelect {...bind('status')}>
                {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </NativeSelect>
            </Field>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={save.isPending || !form.asset_tag.trim() || !form.name.trim() || !form.customer}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function AssetsPage() {
  const canManage = useCan('assets.manage')
  const [search, setSearch] = useState('')
  const [warranty, setWarranty] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [dialog, setDialog] = useState<Asset | 'new' | null>(null)
  const assets = useAssets({ search: useDebouncedValue(search), warranty, status, page })

  return (
    <div className="space-y-5">
      <PageHeader title="Assets" description="Equipment installed at your customers."
        actions={canManage && <Button onClick={() => setDialog('new')}><Plus /> Register asset</Button>} />
      <div className="flex flex-wrap gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" aria-label="Search assets" placeholder="Tag, name, serial or customer" className="pl-8"
            value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        </div>
        <NativeSelect aria-label="Warranty" className="w-44" value={warranty} onChange={(e) => { setWarranty(e.target.value); setPage(1) }}>
          <option value="">Any warranty</option><option value="active">Under warranty</option><option value="expired">Out of warranty</option>
        </NativeSelect>
        <NativeSelect aria-label="Asset status" className="w-36" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="">Any status</option>
          {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </NativeSelect>
      </div>
      {assets.isError ? <ErrorState error={assets.error} onRetry={() => assets.refetch()} /> : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Asset</TableHead>
                <TableHead className="hidden md:table-cell">Customer</TableHead>
                <TableHead className="hidden lg:table-cell">Model / serial</TableHead>
                <TableHead>Warranty</TableHead>
                <TableHead className="hidden sm:table-cell text-right">Open tickets</TableHead>
                {canManage && <TableHead className="w-12"><span className="sr-only">Actions</span></TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {assets.isPending
                ? Array.from({ length: 6 }, (_, i) => <TableRow key={i}><TableCell colSpan={6}><Skeleton className="h-8" /></TableCell></TableRow>)
                : assets.data.results.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell>
                        <span className="font-mono text-xs text-muted-foreground">{a.asset_tag}</span>
                        <span className="block font-medium">{a.name}</span>
                        {a.status !== 'active' && <Badge variant="outline" className="mt-1">{STATUS_LABEL[a.status]}</Badge>}
                      </TableCell>
                      <TableCell className="hidden md:table-cell"><Link to={`/customers/${a.customer}`} className="hover:underline">{a.customer_name}</Link></TableCell>
                      <TableCell className="hidden lg:table-cell">
                        {[a.manufacturer, a.model].filter(Boolean).join(' ') || '—'}
                        {a.serial_number && <span className="block font-mono text-xs text-muted-foreground">{a.serial_number}</span>}
                      </TableCell>
                      <TableCell className={a.under_warranty ? 'text-success' : 'text-muted-foreground'}>
                        {a.warranty_expires_at ? `${a.under_warranty ? 'Until' : 'Ended'} ${formatDate(a.warranty_expires_at)}` : '—'}
                      </TableCell>
                      <TableCell className="hidden text-right tabular-nums sm:table-cell">{a.open_ticket_count ?? 0}</TableCell>
                      {canManage && (
                        <TableCell><Button size="icon-sm" variant="ghost" aria-label={`Edit ${a.asset_tag}`} onClick={() => setDialog(a)}><Pencil /></Button></TableCell>
                      )}
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
          {assets.data?.count === 0 && <EmptyState icon={Boxes} className="m-4" title="No assets match" />}
        </div>
      )}
      {assets.data && assets.data.count > 25 && (
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" disabled={!assets.data.previous} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <Button variant="outline" size="sm" disabled={!assets.data.next} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}
      {dialog && <AssetDialog asset={dialog === 'new' ? undefined : dialog} onClose={() => setDialog(null)} />}
    </div>
  )
}
