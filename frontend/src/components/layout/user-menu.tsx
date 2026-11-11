import { LogOut, UserRound } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { initials } from '@/lib/initials'
import { useAuthStore } from '@/stores/auth'

export function UserMenu() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  if (!user) return null

  const signOut = async () => {
    await logout()
    queryClient.clear() // drop every cached response from this session
    navigate('/login', { replace: true })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" className="rounded-full" aria-label="Account menu" />}>
        <Avatar className="size-7">
          <AvatarFallback className="text-xs">{initials(user.full_name)}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal">
            <div className="truncate text-sm font-medium text-foreground">{user.full_name}</div>
            <div className="truncate text-xs text-muted-foreground">{user.email}</div>
            <div className="mt-1 truncate text-xs text-muted-foreground">{user.role.name} · {user.organization.name}</div>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => navigate('/settings/profile')}><UserRound /> Profile settings</DropdownMenuItem>
        <DropdownMenuItem onClick={signOut}><LogOut /> Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
