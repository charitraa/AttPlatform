import { NavLink } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { navigation } from '@/config/navigation'
import { cn } from '@/lib/utils'
import { hasAnyPermission, useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'

export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2 px-1">
      <div className="grid size-7 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground">AT</div>
      {!collapsed && <span className="text-sm font-semibold tracking-tight">ATT Platform</span>}
    </div>
  )
}

export function NavList({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const user = useAuthStore((s) => s.user)
  // Navigation mirrors permissions for usability; the API enforces access regardless.
  const groups = navigation
    .map((g) => ({ ...g, items: g.items.filter((i) => hasAnyPermission(user, i.permissions ?? [])) }))
    .filter((g) => g.items.length > 0)

  return (
    <nav aria-label="Main" className="flex flex-col gap-5">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col gap-0.5">
          {!collapsed && (
            <p className="px-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{group.label}</p>
          )}
          {group.items.map((item) => {
            const link = (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                onClick={onNavigate}
                aria-label={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  cn(
                    'flex h-8 items-center gap-2.5 rounded-md px-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                    isActive && 'bg-sidebar-accent font-medium text-sidebar-accent-foreground',
                    collapsed && 'justify-center px-0',
                  )
                }
              >
                <item.icon className="size-4 shrink-0" aria-hidden />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            )
            return collapsed ? (
              <Tooltip key={item.to}>
                <TooltipTrigger render={link} />
                <TooltipContent side="right">{item.label}</TooltipContent>
              </Tooltip>
            ) : (
              link
            )
          })}
        </div>
      ))}
    </nav>
  )
}

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const toggle = useUIStore((s) => s.toggleSidebar)

  return (
    <aside
      data-collapsed={collapsed}
      className={cn(
        'sticky top-0 hidden h-svh shrink-0 flex-col border-r bg-sidebar transition-[width] duration-200 md:flex',
        collapsed ? 'w-14' : 'w-60',
      )}
    >
      <div className={cn('flex h-14 items-center border-b px-3', collapsed && 'justify-center px-0')}>
        <Brand collapsed={collapsed} />
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-4">
        <NavList collapsed={collapsed} />
      </div>
      <div className={cn('border-t p-2', collapsed && 'flex justify-center')}>
        <Button
          variant="ghost"
          size={collapsed ? 'icon' : 'sm'}
          className={cn(!collapsed && 'w-full justify-start text-muted-foreground')}
          onClick={toggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <PanelLeftOpen /> : <><PanelLeftClose /> Collapse</>}
        </Button>
      </div>
    </aside>
  )
}
