import { useId, type ComponentProps, type ReactNode } from 'react'

export function CheckboxField({ label, description, ...props }: ComponentProps<'input'> & { label: string; description?: ReactNode }) {
  const id = useId()
  return (
    <div className="flex items-start gap-2.5">
      <input id={id} type="checkbox" className="mt-0.5 size-4 rounded border-input accent-primary" {...props} />
      <div className="grid gap-0.5">
        <label htmlFor={id} className="text-sm font-medium leading-none">{label}</label>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>
    </div>
  )
}
