import { Wrench } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useWorkOrders } from '@/features/field-service/api'
import { WOStatusBadge } from '@/features/field-service/components/wo-parts'

/** On-site work for this ticket (including work orders the AI autopilot created). Hidden when there is none. */
export function TicketWorkOrders({ ticketId }: { ticketId: string }) {
  const list = useWorkOrders({ ticket: ticketId })
  const items = list.data?.results ?? []
  if (items.length === 0) return null
  return (
    <Card>
      <CardHeader><CardTitle>Work orders</CardTitle></CardHeader>
      <CardContent>
        <ul className="divide-y text-sm">
          {items.map((wo) => (
            <li key={wo.id} className="flex items-center justify-between gap-2 py-2">
              <div className="min-w-0">
                <Link to={`/work-orders/${wo.id}`} className="font-mono text-xs font-medium hover:underline">{wo.reference}</Link>
                <p className="flex items-center gap-1 truncate text-muted-foreground">
                  <Wrench className="size-3 shrink-0" aria-hidden />{wo.technician?.name ?? 'Unassigned'}
                </p>
              </div>
              <WOStatusBadge status={wo.status} />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
