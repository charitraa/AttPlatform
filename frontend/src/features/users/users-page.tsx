import { zodResolver } from '@hookform/resolvers/zod'
import { MoreHorizontal, RotateCw, Search, UserPlus, Users as UsersIcon } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { ApiError } from '@/lib/api/client'
import { formatDate, formatRelative } from '@/lib/format'
import { initials } from '@/lib/initials'
import { applyServerErrors } from '@/lib/forms'
import { useAuthStore, useCan } from '@/stores/auth'
import {
  type Invitation, type Member, type Role, useInvitations, useInvite, useMembers, useResendInvitation,
  useRevokeInvitation, useRoles, useUpdateMember,
} from './api'

const PAGE_SIZE = 25
const errorMessage = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')

// ------------------------------------------------------------------ invite dialog
const inviteSchema = z.object({ email: z.email('Enter a valid email address.'), role: z.string().min(1, 'Choose a role.') })
type InviteValues = z.infer<typeof inviteSchema>

function InviteDialog({ open, onOpenChange, roles }: { open: boolean; onOpenChange: (o: boolean) => void; roles: Role[] }) {
  const invite = useInvite()
  const [formError, setFormError] = useState<string | null>(null)
  const assignable = roles.filter((r) => r.assignable)
  const defaultRole = assignable.find((r) => r.code === 'support_agent')?.code ?? assignable[0]?.code ?? ''
  const { register, handleSubmit, setError, reset, formState: { errors, isSubmitting } } = useForm<InviteValues>({
    resolver: zodResolver(inviteSchema),
    values: { email: '', role: defaultRole },
  })

  const close = (o: boolean) => {
    if (!o) {
      reset()
      setFormError(null)
    }
    onOpenChange(o)
  }

  const onSubmit = async (values: InviteValues) => {
    setFormError(null)
    try {
      await invite.mutateAsync(values)
      toast.success(`Invitation sent to ${values.email}`)
      close(false)
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ['email', 'role']))
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a user</DialogTitle>
          <DialogDescription>They'll get an email with a link to join. The link expires after 7 days.</DialogDescription>
        </DialogHeader>
        <form id="invite-form" onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
          <FormError message={formError} />
          <Field label="Email" error={errors.email?.message}>
            <Input type="email" autoComplete="off" autoFocus {...register('email')} />
          </Field>
          <Field label="Role" error={errors.role?.message} description="You can only grant roles up to your own.">
            <NativeSelect {...register('role')}>
              {assignable.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
            </NativeSelect>
          </Field>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>Cancel</Button>
          <Button type="submit" form="invite-form" disabled={isSubmitting}>{isSubmitting ? 'Sending…' : 'Send invitation'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------- change role dialog
function ChangeRoleDialog({ member, roles, onClose }: { member: Member | null; roles: Role[]; onClose: () => void }) {
  const update = useUpdateMember()
  const [role, setRole] = useState('')
  const [error, setError] = useState<string | null>(null)
  const current = member?.role.code ?? ''
  const selected = role || current

  const save = async () => {
    if (!member) return
    setError(null)
    try {
      await update.mutateAsync({ id: member.id, role: selected })
      toast.success(`${member.user.full_name} is now ${roles.find((r) => r.code === selected)?.name ?? selected}`)
      onClose()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <Dialog open={!!member} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change role</DialogTitle>
          <DialogDescription>{member?.user.full_name} ({member?.user.email})</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <FormError message={error} />
          <Field label="Role" description={roles.find((r) => r.code === selected)?.description}>
            <NativeSelect value={selected} onChange={(e) => setRole(e.target.value)}>
              {roles.filter((r) => r.assignable || r.code === current).map((r) => (
                <option key={r.code} value={r.code} disabled={!r.assignable}>{r.name}</option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={update.isPending || selected === current}>{update.isPending ? 'Saving…' : 'Save role'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------- members table
function StatusBadge({ active }: { active: boolean }) {
  return active ? <Badge variant="secondary">Active</Badge> : <Badge variant="outline" className="text-muted-foreground">Deactivated</Badge>
}

function MembersTab({ roles }: { roles: Role[] }) {
  const canManage = useCan('users.manage')
  const selfId = useAuthStore((s) => s.user?.id)
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const debouncedSearch = useDebouncedValue(search)
  const members = useMembers({ search: debouncedSearch, role, is_active: status, page })
  const update = useUpdateMember()
  const [roleTarget, setRoleTarget] = useState<Member | null>(null)
  const [statusTarget, setStatusTarget] = useState<Member | null>(null)

  const resetPage = <T,>(setter: (v: T) => void) => (v: T) => { setter(v); setPage(1) }
  const totalPages = members.data ? Math.max(1, Math.ceil(members.data.count / PAGE_SIZE)) : 1

  const toggleStatus = async () => {
    if (!statusTarget) return
    const activate = !statusTarget.is_active
    try {
      await update.mutateAsync({ id: statusTarget.id, is_active: activate })
      toast.success(`${statusTarget.user.full_name} ${activate ? 'reactivated' : 'deactivated'}`)
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setStatusTarget(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" placeholder="Search name or email" aria-label="Search users" className="pl-8"
            value={search} onChange={(e) => resetPage(setSearch)(e.target.value)} />
        </div>
        <NativeSelect aria-label="Filter by role" className="sm:w-48" value={role} onChange={(e) => resetPage(setRole)(e.target.value)}>
          <option value="">All roles</option>
          {roles.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="Filter by status" className="sm:w-40" value={status} onChange={(e) => resetPage(setStatus)(e.target.value)}>
          <option value="">Any status</option>
          <option value="true">Active</option>
          <option value="false">Deactivated</option>
        </NativeSelect>
      </div>

      {members.isError ? (
        <ErrorState error={members.error} onRetry={() => members.refetch()} />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Role</TableHead>
                <TableHead className="hidden md:table-cell">Status</TableHead>
                <TableHead className="hidden lg:table-cell">Last sign-in</TableHead>
                <TableHead className="hidden lg:table-cell">Joined</TableHead>
                {canManage && <TableHead className="w-12"><span className="sr-only">Actions</span></TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.isPending
                ? Array.from({ length: 5 }, (_, i) => (
                    <TableRow key={i}><TableCell colSpan={6}><Skeleton className="h-8" /></TableCell></TableRow>
                  ))
                : members.data.results.map((m) => (
                    <TableRow key={m.id} className={!m.is_active ? 'text-muted-foreground' : undefined}>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <Avatar className="size-8"><AvatarFallback className="text-xs">{initials(m.user.full_name)}</AvatarFallback></Avatar>
                          <div className="min-w-0">
                            <div className="truncate font-medium">{m.user.full_name}{m.id === selfId && <span className="ml-1.5 text-xs text-muted-foreground">(you)</span>}</div>
                            <div className="truncate text-xs text-muted-foreground">{m.user.email}</div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>{m.role.name}</TableCell>
                      <TableCell className="hidden md:table-cell"><StatusBadge active={m.is_active} /></TableCell>
                      <TableCell className="hidden lg:table-cell">{formatRelative(m.user.last_login)}</TableCell>
                      <TableCell className="hidden lg:table-cell">{formatDate(m.joined_at)}</TableCell>
                      {canManage && (
                        <TableCell>
                          {m.id !== selfId && (
                            <DropdownMenu>
                              <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={`Actions for ${m.user.full_name}`} />}>
                                <MoreHorizontal />
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => setRoleTarget(m)}>Change role</DropdownMenuItem>
                                <DropdownMenuItem onClick={() => setStatusTarget(m)}>{m.is_active ? 'Deactivate' : 'Reactivate'}</DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
          {members.data && members.data.count === 0 && (
            <EmptyState icon={UsersIcon} className="m-4" title="No users match these filters" />
          )}
        </div>
      )}

      {members.data && members.data.count > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{members.data.count} users · page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={!members.data.previous} onClick={() => setPage((p) => p - 1)}>Previous</Button>
            <Button variant="outline" size="sm" disabled={!members.data.next} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      )}

      {/* keyed so the selection resets for each member */}
      <ChangeRoleDialog key={roleTarget?.id ?? 'none'} member={roleTarget} roles={roles} onClose={() => setRoleTarget(null)} />
      <AlertDialog open={!!statusTarget} onOpenChange={(o) => { if (!o) setStatusTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{statusTarget?.is_active ? 'Deactivate' : 'Reactivate'} {statusTarget?.user.full_name}?</AlertDialogTitle>
            <AlertDialogDescription>
              {statusTarget?.is_active
                ? 'They will be signed out immediately and lose access to this organization. Their history is kept, and you can reactivate them later.'
                : 'They will be able to sign in to this organization again with their existing role.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant={statusTarget?.is_active ? 'destructive' : 'default'} onClick={toggleStatus} disabled={update.isPending}>
              {statusTarget?.is_active ? 'Deactivate' : 'Reactivate'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// ----------------------------------------------------------- invitations table
const INVITE_STATUS_STYLE: Record<Invitation['status'], string> = {
  pending: 'border-primary/40 text-primary',
  accepted: 'text-success border-success/40',
  revoked: 'text-muted-foreground',
  expired: 'text-warning border-warning/40',
}

function InvitationsTab() {
  const [status, setStatus] = useState('pending')
  const invitations = useInvitations(status)
  const revoke = useRevokeInvitation()
  const resend = useResendInvitation()
  const [revokeTarget, setRevokeTarget] = useState<Invitation | null>(null)

  const doResend = async (inv: Invitation) => {
    try {
      await resend.mutateAsync(inv.id)
      toast.success(`Invitation re-sent to ${inv.email}. The previous link no longer works.`)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  const doRevoke = async () => {
    if (!revokeTarget) return
    try {
      await revoke.mutateAsync(revokeTarget.id)
      toast.success(`Invitation for ${revokeTarget.email} revoked`)
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setRevokeTarget(null)
    }
  }

  return (
    <div className="space-y-4">
      <NativeSelect aria-label="Filter invitations" className="sm:w-48" value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="pending">Pending</option>
        <option value="accepted">Accepted</option>
        <option value="expired">Expired</option>
        <option value="revoked">Revoked</option>
        <option value="">All</option>
      </NativeSelect>
      {invitations.isError ? (
        <ErrorState error={invitations.error} onRetry={() => invitations.refetch()} />
      ) : invitations.isPending ? (
        <Skeleton className="h-32" />
      ) : invitations.data.count === 0 ? (
        <EmptyState icon={UserPlus} title={`No ${status || ''} invitations`.replace('  ', ' ')} description="Invite teammates with the Invite user button." />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Invited by</TableHead>
                <TableHead className="hidden md:table-cell">Expires</TableHead>
                <TableHead className="w-32"><span className="sr-only">Actions</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitations.data.results.map((inv) => (
                <TableRow key={inv.id}>
                  <TableCell className="font-medium">{inv.email}</TableCell>
                  <TableCell>{inv.role.name}</TableCell>
                  <TableCell><Badge variant="outline" className={`capitalize ${INVITE_STATUS_STYLE[inv.status]}`}>{inv.status}</Badge></TableCell>
                  <TableCell className="hidden md:table-cell">{inv.invited_by ?? '—'}</TableCell>
                  <TableCell className="hidden md:table-cell">{formatDate(inv.expires_at)}</TableCell>
                  <TableCell className="text-right">
                    {(inv.status === 'pending' || inv.status === 'expired') && (
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => doResend(inv)} disabled={resend.isPending}><RotateCw /> Resend</Button>
                        <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setRevokeTarget(inv)}>Revoke</Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <AlertDialog open={!!revokeTarget} onOpenChange={(o) => { if (!o) setRevokeTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke invitation?</AlertDialogTitle>
            <AlertDialogDescription>The link sent to {revokeTarget?.email} will stop working immediately.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={doRevoke}>Revoke</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export function UsersPage() {
  const canInvite = useCan('invitations.manage')
  const roles = useRoles()
  const [inviteOpen, setInviteOpen] = useState(false)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description="Members of your organization and their roles."
        actions={canInvite && <Button onClick={() => setInviteOpen(true)} disabled={!roles.data}><UserPlus /> Invite user</Button>}
      />
      {roles.isError ? (
        <ErrorState error={roles.error} onRetry={() => roles.refetch()} />
      ) : canInvite ? (
        <Tabs defaultValue="members">
          <TabsList>
            <TabsTrigger value="members">Members</TabsTrigger>
            <TabsTrigger value="invitations">Invitations</TabsTrigger>
          </TabsList>
          <TabsContent value="members" className="pt-4"><MembersTab roles={roles.data ?? []} /></TabsContent>
          <TabsContent value="invitations" className="pt-4"><InvitationsTab /></TabsContent>
        </Tabs>
      ) : (
        <MembersTab roles={roles.data ?? []} />
      )}
      {canInvite && roles.data && <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} roles={roles.data} />}
    </div>
  )
}
