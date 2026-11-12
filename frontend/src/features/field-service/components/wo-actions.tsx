import { CalendarClock, CheckCircle2, PenLine, Undo2, UserPlus, XCircle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { firstErrorMessage } from '@/lib/forms'
import { cn } from '@/lib/utils'
import { STEP_LABEL, type WorkOrder, useAdvance } from '../api'
import { AssignDialog, CompleteDialog, ConfirmDialog, ReasonDialog, ScheduleDialog } from './wo-dialogs'

type DialogKind = 'assign' | 'schedule' | 'decline' | 'cancel' | 'complete' | 'confirm' | null

/** Current position if the technician shares location; resolves to undefined otherwise (never blocks). */
async function currentPosition(): Promise<{ lat: string; lng: string } | undefined> {
  if (!('geolocation' in navigator)) return undefined
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude.toFixed(6), lng: p.coords.longitude.toFixed(6) }),
      () => resolve(undefined),
      { timeout: 4000, maximumAge: 60_000 },
    )
  })
}

export function WOActions({ wo, size = 'sm', shareLocation = false, className }: {
  wo: WorkOrder; size?: 'sm' | 'lg'; shareLocation?: boolean; className?: string
}) {
  const advance = useAdvance(wo.id)
  const [dialog, setDialog] = useState<DialogKind>(null)
  const caps = wo.capabilities
  const fieldSteps = wo.next_steps.filter((s) => s !== 'cancelled')
  const [primary, ...alternatives] = fieldSteps

  const step = async (to: string) => {
    if (to === 'completed') return setDialog('complete')
    try {
      const where = shareLocation && ['en_route', 'on_site'].includes(to) ? await currentPosition() : undefined
      await advance.mutateAsync({ status: to, ...where })
      toast.success(STEP_LABEL[to] ?? to)
    } catch (e) {
      toast.error(firstErrorMessage(e))
    }
  }

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      {primary && (
        <Button size={size} onClick={() => step(primary)} disabled={advance.isPending}>
          {primary === 'completed' && <CheckCircle2 />} {STEP_LABEL[primary] ?? primary}
        </Button>
      )}
      {alternatives.map((s) => (
        <Button key={s} size={size} variant="outline" onClick={() => step(s)} disabled={advance.isPending}>{STEP_LABEL[s] ?? s}</Button>
      ))}
      {caps.confirm && <Button size={size} onClick={() => setDialog('confirm')}><PenLine /> Customer sign-off</Button>}
      {caps.assign && <Button size={size} variant="outline" onClick={() => setDialog('assign')}><UserPlus /> {wo.technician ? 'Reassign' : 'Assign'}</Button>}
      {caps.schedule && <Button size={size} variant="outline" onClick={() => setDialog('schedule')}><CalendarClock /> {wo.appointment ? 'Reschedule' : 'Schedule'}</Button>}
      {caps.decline && <Button size={size} variant="ghost" onClick={() => setDialog('decline')}><Undo2 /> Hand back</Button>}
      {wo.next_steps.includes('cancelled') && <Button size={size} variant="ghost" className="text-destructive" onClick={() => setDialog('cancel')}><XCircle /> Cancel</Button>}

      {dialog === 'assign' && <AssignDialog wo={wo} onClose={() => setDialog(null)} />}
      {dialog === 'schedule' && <ScheduleDialog wo={wo} onClose={() => setDialog(null)} />}
      {(dialog === 'decline' || dialog === 'cancel') && <ReasonDialog wo={wo} mode={dialog} onClose={() => setDialog(null)} />}
      {dialog === 'complete' && <CompleteDialog wo={wo} onClose={() => setDialog(null)} />}
      {dialog === 'confirm' && <ConfirmDialog wo={wo} onClose={() => setDialog(null)} />}
    </div>
  )
}
