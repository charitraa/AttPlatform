import { ChevronRight, LifeBuoy, Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { formatDateTime, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import { usePortalTickets } from './api'
import { PortalStatus } from './components'

const TABS = [{ value: 'open', label: 'Open' }, { value: 'done', label: 'Resolved' }, { value: '', label: 'All' }] as const

export function PortalHomePage() {
  const name = useAuthStore((s) => s.user?.first_name)
  const [state, setState] = useState<'open' | 'done' | ''>('open')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const list = usePortalTickets({ state, search: useDebouncedValue(search), page })

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title={name ? `Hello, ${name}` : 'Your requests'} description="Raise a request, follow its progress and reply to our team."
        actions={<Button render={<Link to="/portal/new" />} nativeButton={false}><Plus /> New request</Button>} />
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Requests" className="inline-flex rounded-md border p-0.5">
          {TABS.map((t) => (
            <button key={t.label} role="tab" type="button" aria-selected={state === t.value}
              className={cn('rounded px-3 py-1 text-sm', state === t.value ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground')}
              onClick={() => { setState(t.value); setPage(1) }}>{t.label}</button>
          ))}
        </div>
        <div className="relative ml-auto w-full sm:w-64">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" aria-label="Search your requests" placeholder="Search" className="pl-8" value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        </div>
      </div>
      {list.isPending ? <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}</div> :
        list.isError ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> :
        list.data.count === 0 ? (
          <EmptyState icon={LifeBuoy} title={state === 'open' ? 'No open requests' : 'Nothing here yet'}
            description="Tell us what's wrong and we'll take it from there."
            action={<Button render={<Link to="/portal/new" />} nativeButton={false}><Plus /> New request</Button>} />
        ) : (
          <>
            <ul className="space-y-2">
              {list.data.results.map((t) => (
                <li key={t.id}>
                  <Link to={`/portal/tickets/${t.id}`} className="flex items-center gap-3 rounded-xl border bg-card p-4 transition-colors hover:bg-muted/40">
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-muted-foreground">{t.reference}</span>
                        <PortalStatus label={t.status_label} />
                        {t.actions.rate && <span className="text-xs font-medium text-primary">Rate our help</span>}
                      </div>
                      <p className="truncate font-medium">{t.title}</p>
                      <p className="text-xs text-muted-foreground" title={formatDateTime(t.updated_at)}>Updated {formatRelative(t.updated_at)}</p>
                    </div>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
            {(list.data.next || list.data.previous) && (
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" disabled={!list.data.previous} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button variant="outline" size="sm" disabled={!list.data.next} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            )}
          </>
        )}
    </div>
  )
}
