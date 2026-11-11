import { AlertCircle } from 'lucide-react'

/** Form-level error banner (non-field errors from the API). */
export function FormError({ message }: { message?: string | null }) {
  if (!message) return null
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  )
}
