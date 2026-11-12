import { Search, Wrench } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { StatusDot } from '@/components/common/status-indicator'
import { NativeSelect } from '@/components/forms/native-select'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { initials } from '@/lib/initials'
import { TECH_STATUS_LABEL, useTechnicians } from './api'
import { TECH_HEALTH } from './utils'

export function TechniciansPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const techs = useTechnicians({ search: useDebouncedValue(search), status })
  return (
    <div className="space-y-5">
      <PageHeader title="Technicians" description="Field team, skills and today's workload. Anyone given the Field Technician role appears here." />
      <div className="flex flex-wrap gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" aria-label="Search technicians" placeholder="Name, email or skill" className="pl-8" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <NativeSelect aria-label="Technician status" className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          {Object.entries(TECH_STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </NativeSelect>
      </div>
      {techs.isPending ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}</div> :
        techs.isError ? <ErrorState error={techs.error} onRetry={() => techs.refetch()} /> :
        techs.data.count === 0 ? <EmptyState icon={Wrench} title="No technicians found" description="Invite users with the Field Technician role from the Users page." /> : (
          <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {techs.data.results.map((t) => (
              <li key={t.id}>
                <Link to={`/technicians/${t.id}`} className="block h-full rounded-xl border bg-card p-4 transition-colors hover:bg-muted/40">
                  <div className="flex items-start gap-3">
                    <Avatar className="size-10"><AvatarFallback>{initials(t.user.full_name)}</AvatarFallback></Avatar>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{t.user.full_name}</div>
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><StatusDot health={TECH_HEALTH[t.status]} /> {TECH_STATUS_LABEL[t.status]}{t.employee_id && ` · ${t.employee_id}`}</div>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1">
                    {t.skills.length ? t.skills.map((s) => <Badge key={s.skill} variant="secondary">{s.name} · {s.level}</Badge>) : <span className="text-xs text-muted-foreground">No skills recorded</span>}
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-2 border-t pt-3 text-xs">
                    <div><dt className="text-muted-foreground">Open jobs</dt><dd className="text-base font-semibold tabular-nums">{t.active_jobs}</dd></div>
                    <div><dt className="text-muted-foreground">Visits today</dt><dd className="text-base font-semibold tabular-nums">{t.jobs_today} <span className="text-xs font-normal text-muted-foreground">/ {t.max_daily_jobs}</span></dd></div>
                  </dl>
                </Link>
              </li>
            ))}
          </ul>
        )}
    </div>
  )
}
