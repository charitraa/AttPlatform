import { cn } from '@/lib/utils'

export type Health = 'ok' | 'warning' | 'error' | 'unknown'

const styles: Record<Health, string> = {
  ok: 'bg-success',
  warning: 'bg-warning',
  error: 'bg-destructive',
  unknown: 'bg-muted-foreground/40',
}

export function StatusDot({ health, className }: { health: Health; className?: string }) {
  return <span aria-hidden className={cn('inline-block size-2 shrink-0 rounded-full', styles[health], className)} />
}
