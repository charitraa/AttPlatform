import { History } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime, formatRelative } from '@/lib/format'
import { useHistory } from '../api'
import { describeEvent } from '../describe-event'

export function Timeline({ ticketId }: { ticketId: string }) {
  const history = useHistory(ticketId)
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><History className="size-4" /> Activity</CardTitle></CardHeader>
      <CardContent>
        {history.isPending ? <Skeleton className="h-24" /> : (
          <ol className="relative space-y-4 border-l pl-4">
            {[...(history.data ?? [])].reverse().map((h) => (
              <li key={h.id} className="relative text-sm">
                <span className="absolute top-1.5 -left-[21px] size-2 rounded-full bg-border ring-4 ring-card" aria-hidden />
                <span className="font-medium">{h.actor?.full_name ?? (h.actor_type === 'ai' ? 'AI' : 'System')}</span>{' '}
                <span className="text-muted-foreground">{describeEvent(h)}</span>
                <time className="block text-xs text-muted-foreground" dateTime={h.created_at} title={formatDateTime(h.created_at)}>{formatRelative(h.created_at)}</time>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}
