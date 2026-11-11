import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from 'react'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

interface FieldProps {
  label: string
  error?: string
  description?: ReactNode
  className?: string
  /** A single form control; it receives id, aria-invalid and aria-describedby. */
  children: ReactElement<Record<string, unknown>>
}

export function Field({ label, error, description, className, children }: FieldProps) {
  const id = useId()
  const descriptionId = description ? `${id}-description` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [descriptionId, errorId].filter(Boolean).join(' ') || undefined

  return (
    <div className={cn('grid gap-1.5', className)}>
      <Label htmlFor={id}>{label}</Label>
      {isValidElement(children)
        ? cloneElement(children, { id, 'aria-invalid': error ? true : undefined, 'aria-describedby': describedBy })
        : children}
      {description && !error && <p id={descriptionId} className="text-xs text-muted-foreground">{description}</p>}
      {error && <p id={errorId} role="alert" className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
