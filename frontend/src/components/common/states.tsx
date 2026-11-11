import type { LucideIcon } from 'lucide-react'
import { AlertTriangle, Inbox, RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api/client'
import { cn } from '@/lib/utils'

export function EmptyState({ icon: Icon = Inbox, title, description, action, className }: {
  icon?: LucideIcon
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-12 text-center', className)}>
      <Icon className="size-8 text-muted-foreground" aria-hidden />
      <h3 className="text-sm font-medium">{title}</h3>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  const requestId = error instanceof ApiError ? error.requestId : null
  return (
    <div role="alert" className={cn('flex flex-col items-center justify-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-10 text-center', className)}>
      <AlertTriangle className="size-7 text-destructive" aria-hidden />
      <h3 className="text-sm font-medium">Couldn't load this data</h3>
      <p className="max-w-md text-sm text-muted-foreground">{message}</p>
      {requestId && <p className="font-mono text-xs text-muted-foreground">Request ID: {requestId}</p>}
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
          <RotateCw /> Retry
        </Button>
      )}
    </div>
  )
}
