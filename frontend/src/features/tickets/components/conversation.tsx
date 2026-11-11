import { Lock, MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api/client'
import { formatDateTime, formatRelative } from '@/lib/format'
import { initials } from '@/lib/initials'
import { cn } from '@/lib/utils'
import { type Ticket, useAddComment, useComments } from '../api'

function Composer({ ticket }: { ticket: Ticket }) {
  const add = useAddComment(ticket.id)
  const [body, setBody] = useState('')
  const [visibility, setVisibility] = useState<'public' | 'internal'>('public')
  const internal = visibility === 'internal'

  const send = async () => {
    try {
      await add.mutateAsync({ body, visibility })
      setBody('')
      toast.success(internal ? 'Internal note added' : 'Reply sent')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Could not send the message.')
    }
  }

  return (
    <div className={cn('rounded-lg border p-3', internal && 'border-warning/50 bg-warning/5')}>
      {ticket.capabilities.internal_notes && (
        <div role="radiogroup" aria-label="Message type" className="mb-2 flex gap-1">
          {(['public', 'internal'] as const).map((v) => (
            <button key={v} type="button" role="radio" aria-checked={visibility === v} onClick={() => setVisibility(v)}
              className={cn('rounded-md px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground',
                visibility === v && 'bg-muted text-foreground')}>
              {v === 'public' ? 'Reply to customer' : 'Internal note'}
            </button>
          ))}
        </div>
      )}
      <Textarea aria-label={internal ? 'Internal note' : 'Reply'} rows={3} value={body} onChange={(e) => setBody(e.target.value)}
        placeholder={internal ? 'Only staff can see this note.' : 'Write a reply…'}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && body.trim()) void send() }} />
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{internal ? <span className="inline-flex items-center gap-1"><Lock className="size-3" /> Hidden from the customer</span> : 'Ctrl/⌘ + Enter to send'}</span>
        <Button size="sm" onClick={send} disabled={!body.trim() || add.isPending}>{add.isPending ? 'Sending…' : internal ? 'Add note' : 'Send reply'}</Button>
      </div>
    </div>
  )
}

export function Conversation({ ticket }: { ticket: Ticket }) {
  const comments = useComments(ticket.id)
  return (
    <section aria-labelledby="conversation-heading" className="space-y-4">
      <h2 id="conversation-heading" className="text-sm font-semibold">Conversation</h2>
      {comments.isPending ? (
        <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
      ) : comments.isError ? (
        <ErrorState error={comments.error} onRetry={() => comments.refetch()} />
      ) : comments.data.length === 0 ? (
        <EmptyState icon={MessageSquare} title="No messages yet" className="py-8" />
      ) : (
        <ol className="space-y-3">
          {comments.data.map((c) => {
            const internal = c.visibility === 'internal'
            return (
              <li key={c.id} className={cn('flex gap-3 rounded-lg border p-3', internal && 'border-warning/40 bg-warning/5')}>
                <Avatar className="size-8"><AvatarFallback className="text-xs">{initials(c.author?.full_name ?? 'System')}</AvatarFallback></Avatar>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                    <span className="font-medium">{c.author?.full_name ?? 'System'}</span>
                    {c.source === 'customer' && <span className="text-xs text-muted-foreground">Customer</span>}
                    {internal && <span className="inline-flex items-center gap-1 text-xs font-medium text-warning"><Lock className="size-3" aria-hidden /> Internal note</span>}
                    <time className="text-xs text-muted-foreground" dateTime={c.created_at} title={formatDateTime(c.created_at)}>{formatRelative(c.created_at)}</time>
                  </div>
                  <p className="mt-1 text-sm break-words whitespace-pre-wrap">{c.body}</p>
                </div>
              </li>
            )
          })}
        </ol>
      )}
      {ticket.capabilities.comment ? <Composer ticket={ticket} /> : (
        <p className="text-sm text-muted-foreground">{ticket.archived_at ? 'Archived tickets are read-only.' : 'This ticket is closed. Reopen it to reply.'}</p>
      )}
    </section>
  )
}
