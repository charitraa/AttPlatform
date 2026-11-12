import { Bell, CheckCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useMarkRead, useNotifications, useUnreadCount } from './api'

export function NotificationBell() {
  const navigate = useNavigate()
  const unread = useUnreadCount().data?.unread ?? 0
  const recent = useNotifications({ page_size: 6 })
  const mark = useMarkRead()
  const label = unread ? `Notifications, ${unread} unread` : 'Notifications'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" className="relative" aria-label={label} />}>
        <Bell />
        {unread > 0 && (
          <span aria-hidden className="absolute top-1 right-1 flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] leading-4 font-semibold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex items-center justify-between font-normal">
            <span className="text-sm font-medium text-foreground">Notifications</span>
            {unread > 0 && (
              <button type="button" className="inline-flex items-center gap-1 text-xs text-primary hover:underline" onClick={() => mark.all.mutate()}>
                <CheckCheck className="size-3.5" aria-hidden /> Mark all read
              </button>
            )}
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        {recent.data?.results.length ? recent.data.results.map((n) => (
          <DropdownMenuItem key={n.id} className="items-start gap-2 py-2"
            onClick={() => { if (!n.is_read) mark.one.mutate(n.id); if (n.link) navigate(n.link) }}>
            <span aria-hidden className={cn('mt-1.5 size-2 shrink-0 rounded-full', n.is_read ? 'bg-transparent' : 'bg-primary')} />
            <span className="min-w-0">
              <span className={cn('block truncate text-sm', !n.is_read && 'font-medium')}>{n.title}</span>
              {n.body && <span className="block truncate text-xs text-muted-foreground">{n.body}</span>}
              <span className="block text-xs text-muted-foreground">{formatRelative(n.created_at)}{!n.is_read && <span className="sr-only"> · unread</span>}</span>
            </span>
          </DropdownMenuItem>
        )) : (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">{recent.isPending ? 'Loading…' : "You're all caught up."}</p>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => navigate('/notifications')} className="justify-center text-sm">See all notifications</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
