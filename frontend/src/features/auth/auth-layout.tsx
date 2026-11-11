import type { ReactNode } from 'react'
import { Brand } from '@/components/layout/sidebar'

export function AuthLayout({ title, description, children, footer }: {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-muted/40 px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center"><Brand /></div>
        <div className="rounded-xl border bg-card p-6 shadow-sm">
          <div className="mb-5 space-y-1">
            <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
            {description && <p className="text-sm text-muted-foreground">{description}</p>}
          </div>
          {children}
        </div>
        {footer && <div className="mt-4 text-center text-sm text-muted-foreground">{footer}</div>}
      </div>
    </div>
  )
}
