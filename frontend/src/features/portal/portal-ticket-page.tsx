import { ArrowLeft, CheckCircle2, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api/client'
import { formatDateTime, formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { cn } from '@/lib/utils'
import { type PortalTicket, usePortalComments, usePortalMutations, usePortalTicket } from './api'
import { PortalStatus, StarRating } from './components'

function Resolution({ t }: { t: PortalTicket }) {
  const m = usePortalMutations(t.id)
  const [reopening, setReopening] = useState(false)
  const [note, setNote] = useState('')
  const run = async (p: Promise<unknown>, ok: string) => {
    try { await p; toast.success(ok); setReopening(false) } catch (e) { toast.error(firstErrorMessage(e)) }
  }
  if (!t.actions.confirm && !t.actions.reopen) return null
  return (
    <Card className="border-success/40 bg-success/5">
      <CardContent className="space-y-3">
        <p className="font-medium">We think this is fixed.</p>
        {t.resolution_notes && <p className="text-sm whitespace-pre-wrap">{t.resolution_notes}</p>}
        {reopening ? (
          <div className="space-y-2">
            <label htmlFor="reopen-note" className="text-sm font-medium">What's still wrong?</label>
            <Textarea id="reopen-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="flex gap-2">
              <Button disabled={!note.trim() || m.reopen.isPending} onClick={() => run(m.reopen.mutateAsync(note.trim()), 'Request reopened')}>Reopen request</Button>
              <Button variant="ghost" onClick={() => setReopening(false)}>Cancel</Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {t.actions.confirm && <Button disabled={m.confirm.isPending} onClick={() => run(m.confirm.mutateAsync(), 'Thanks for confirming')}><CheckCircle2 /> Yes, it's fixed</Button>}
            {t.actions.reopen && <Button variant="outline" onClick={() => setReopening(true)}><RotateCcw /> No, it's still broken</Button>}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function Rate({ t }: { t: PortalTicket }) {
  const { rate } = usePortalMutations(t.id)
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState('')
  if (t.feedback) {
    return (
      <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        You rated this <StarRating value={t.feedback.rating} /> {t.feedback.comment && <span>“{t.feedback.comment}”</span>}
      </p>
    )
  }
  if (!t.actions.rate) return null
  return (
    <Card>
      <CardHeader><CardTitle>How did we do?</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <StarRating value={rating} onChange={setRating} label="Rate how we handled this request" />
        <Textarea rows={2} aria-label="Anything you'd like to tell us? (optional)" placeholder="Anything you'd like to tell us? (optional)"
          value={comment} onChange={(e) => setComment(e.target.value)} />
        <Button disabled={!rating || rate.isPending}
          onClick={() => rate.mutate({ rating, comment }, { onSuccess: () => toast.success('Thank you for your feedback'), onError: (e) => toast.error(firstErrorMessage(e)) })}>
          Send feedback
        </Button>
      </CardContent>
    </Card>
  )
}

function Conversation({ t }: { t: PortalTicket }) {
  const thread = usePortalComments(t.id)
  const { reply } = usePortalMutations(t.id)
  const [body, setBody] = useState('')
  const waiting = t.status_label === 'Waiting for your reply'
  return (
    <Card>
      <CardHeader><CardTitle>Conversation</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {thread.data?.length === 0 && <p className="text-sm text-muted-foreground">No messages yet. We'll reply here.</p>}
        <ol className="space-y-3">
          {thread.data?.map((c) => (
            <li key={c.id} className={cn('flex', c.from_support ? 'justify-start' : 'justify-end')}>
              <div className={cn('max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm', c.from_support ? 'rounded-tl-sm bg-muted' : 'rounded-tr-sm bg-primary text-primary-foreground')}>
                <p className={cn('mb-0.5 text-xs font-medium', c.from_support ? 'text-muted-foreground' : 'text-primary-foreground/80')}>
                  {c.from_support ? `${c.author} · Support` : 'You'} · <time dateTime={c.created_at} title={formatDateTime(c.created_at)}>{formatRelative(c.created_at)}</time>
                </p>
                <p className="whitespace-pre-wrap break-words">{c.body}</p>
              </div>
            </li>
          ))}
        </ol>
        {t.actions.reply && (
          <form className="space-y-2" onSubmit={(e) => {
            e.preventDefault()
            if (!body.trim()) return
            reply.mutate(body.trim(), { onSuccess: () => setBody(''), onError: (err) => toast.error(firstErrorMessage(err)) })
          }}>
            <label htmlFor="reply" className={cn('text-sm font-medium', waiting && 'text-warning')}>{waiting ? 'We need a reply from you' : 'Add a message'}</label>
            <Textarea id="reply" rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
            <div className="flex justify-end"><Button type="submit" disabled={!body.trim() || reply.isPending}>Send</Button></div>
          </form>
        )}
      </CardContent>
    </Card>
  )
}

export function PortalTicketPage() {
  const { id = '' } = useParams()
  const q = usePortalTicket(id)
  if (q.isPending) return <div className="mx-auto max-w-3xl space-y-4"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-48" /></div>
  if (q.isError) {
    const missing = q.error instanceof ApiError && q.error.status === 404
    return <ErrorState error={missing ? new Error("We couldn't find that request.") : q.error} onRetry={missing ? undefined : () => q.refetch()} />
  }
  const t = q.data
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Link to="/portal" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Your requests</Link>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-muted-foreground">{t.reference}</span>
          <PortalStatus label={t.status_label} />
        </div>
        <h1 className="text-xl font-semibold tracking-tight break-words">{t.title}</h1>
        <p className="text-sm text-muted-foreground">
          Opened {formatDateTime(t.created_at)}{t.handled_by && <> · handled by {t.handled_by}</>}
          {t.category && <> · {t.category}</>}{t.asset && <> · {t.asset.name}</>}
        </p>
      </div>
      <Resolution t={t} />
      <Rate t={t} />
      <Card><CardContent><p className="text-sm whitespace-pre-wrap">{t.description}</p></CardContent></Card>
      <Conversation t={t} />
    </div>
  )
}
