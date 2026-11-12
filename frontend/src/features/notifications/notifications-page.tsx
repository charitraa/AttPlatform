import { BellOff, CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatDateTime, formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { cn } from '@/lib/utils'
import { type Preference, useMarkRead, useNotifications, usePreferences, useSavePreferences, useUnreadCount } from './api'

function Inbox() {
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [page, setPage] = useState(1)
  const list = useNotifications({ unread: unreadOnly, page })
  const unread = useUnreadCount().data?.unread ?? 0
  const mark = useMarkRead()

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Filter" className="inline-flex rounded-md border p-0.5">
          {[false, true].map((u) => (
            <button key={String(u)} type="button" aria-pressed={unreadOnly === u}
              className={cn('rounded px-3 py-1 text-sm', unreadOnly === u ? 'bg-muted font-medium' : 'text-muted-foreground')}
              onClick={() => { setUnreadOnly(u); setPage(1) }}>
              {u ? `Unread (${unread})` : 'All'}
            </button>
          ))}
        </div>
        <Button variant="outline" size="sm" className="ml-auto" disabled={!unread || mark.all.isPending} onClick={() => mark.all.mutate()}>
          <CheckCheck /> Mark all read
        </Button>
      </div>
      {list.isPending ? <Skeleton className="h-64" /> : list.isError ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> :
        list.data.count === 0 ? <EmptyState icon={BellOff} title={unreadOnly ? 'No unread notifications' : 'No notifications yet'} description="Assignments, customer replies and SLA alerts appear here as they happen." /> : (
          <>
            <ul className="divide-y rounded-xl border bg-card">
              {list.data.results.map((n) => {
                const content = (
                  <>
                    <span aria-hidden className={cn('mt-1.5 size-2 shrink-0 rounded-full', n.is_read ? 'bg-transparent' : 'bg-primary')} />
                    <span className="min-w-0 flex-1">
                      <span className={cn('block text-sm', !n.is_read && 'font-medium')}>{n.title}{!n.is_read && <span className="sr-only"> (unread)</span>}</span>
                      {n.body && <span className="block text-sm text-muted-foreground">{n.body}</span>}
                    </span>
                    <time className="shrink-0 text-xs text-muted-foreground" dateTime={n.created_at} title={formatDateTime(n.created_at)}>{formatRelative(n.created_at)}</time>
                  </>
                )
                const onOpen = () => { if (!n.is_read) mark.one.mutate(n.id) }
                return (
                  <li key={n.id}>
                    {n.link
                      ? <Link to={n.link} onClick={onOpen} className="flex items-start gap-3 p-3 hover:bg-muted/40">{content}</Link>
                      : <button type="button" onClick={onOpen} className="flex w-full items-start gap-3 p-3 text-left hover:bg-muted/40">{content}</button>}
                  </li>
                )
              })}
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

function Preferences() {
  const prefs = usePreferences()
  const save = useSavePreferences()
  if (prefs.isPending) return <Skeleton className="h-64" />
  if (prefs.isError) return <ErrorState error={prefs.error} onRetry={() => prefs.refetch()} />
  const rows = new Map<string, { label: string; in_app?: Preference; email?: Preference }>()
  for (const p of prefs.data) rows.set(p.type, { ...rows.get(p.type), label: p.label, [p.channel]: p })
  const toggle = (p: Preference) =>
    save.mutate([{ type: p.type, channel: p.channel, enabled: !p.enabled }], {
      onError: (e) => toast.error(firstErrorMessage(e)),
    })

  return (
    <Card>
      <CardHeader>
        <CardTitle>What you're told about</CardTitle>
        <CardDescription>Changes save straight away. You're never notified about things you did yourself.</CardDescription>
      </CardHeader>
      <CardContent>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground"><th className="py-2 font-medium">Event</th><th className="w-24 py-2 text-center font-medium">In-app</th><th className="w-24 py-2 text-center font-medium">Email</th></tr>
          </thead>
          <tbody>
            {[...rows.entries()].map(([type, row]) => (
              <tr key={type} className="border-b last:border-0">
                <td className="py-2.5">{row.label}</td>
                {(['in_app', 'email'] as const).map((c) => {
                  const p = row[c]
                  return (
                    <td key={c} className="py-2.5 text-center">
                      {p && <input type="checkbox" className="size-4 accent-primary" checked={p.enabled} disabled={save.isPending}
                        aria-label={`${row.label}: ${c === 'email' ? 'email' : 'in-app'}`} onChange={() => toggle(p)} />}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

export function NotificationsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title="Notifications" description="Live updates about your tickets, jobs and SLA deadlines." />
      <Tabs defaultValue="inbox">
        <TabsList>
          <TabsTrigger value="inbox">Inbox</TabsTrigger>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
        </TabsList>
        <TabsContent value="inbox" className="pt-4"><Inbox /></TabsContent>
        <TabsContent value="preferences" className="pt-4"><Preferences /></TabsContent>
      </Tabs>
    </div>
  )
}
