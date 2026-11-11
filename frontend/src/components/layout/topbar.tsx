import { Bell, Menu, Search } from 'lucide-react'
import { Link } from 'react-router-dom'
import { StatusDot } from '@/components/common/status-indicator'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useMeta, useReadiness } from '@/lib/api/system'
import { useUIStore } from '@/stores/ui'
import { Brand, NavList } from './sidebar'
import { ThemeMenu } from './theme-menu'

function ConnectionBadge() {
  const { data, isError } = useReadiness()
  const health = isError ? 'error' : !data ? 'unknown' : data.status === 'ok' ? 'ok' : 'warning'
  const label = { ok: 'All systems operational', warning: 'Degraded', error: 'API unreachable', unknown: 'Checking…' }[health]
  return (
    <Link to="/system" className="hidden items-center gap-2 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted lg:flex">
      <StatusDot health={health} /> {label}
    </Link>
  )
}

export function Topbar() {
  const mobileNavOpen = useUIStore((s) => s.mobileNavOpen)
  const setMobileNavOpen = useUIStore((s) => s.setMobileNavOpen)
  const { data: meta } = useMeta()

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur supports-backdrop-filter:bg-background/80">
      <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}>
        <Menu />
      </Button>
      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="w-64 p-3">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="mb-4 pt-1"><Brand /></div>
          <NavList onNavigate={() => setMobileNavOpen(false)} />
        </SheetContent>
      </Sheet>

      {/* Global search is wired to the backend search API with ticketing (Phase 3). */}
      <div className="relative max-w-md flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          type="search"
          disabled
          aria-label="Global search"
          placeholder="Search tickets, customers, assets…"
          title="Global search becomes available with the ticketing module"
          className="pl-8"
        />
      </div>

      <div className="ml-auto flex items-center gap-1">
        {meta?.ai_mock_mode && (
          <Badge variant="outline" className="hidden border-warning/50 text-warning sm:inline-flex" title="AI results come from the offline mock provider">
            Demo AI
          </Badge>
        )}
        <ConnectionBadge />
        <Button variant="ghost" size="icon" aria-label="Notifications" render={<Link to="/notifications" />}>
          <Bell />
        </Button>
        <ThemeMenu />
      </div>
    </header>
  )
}
