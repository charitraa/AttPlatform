import { CheckCircle2, Clock, MessageCircleQuestion, Star } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

const TONE: Record<string, string> = {
  'Waiting for your reply': 'border-warning/50 bg-warning/10 text-warning',
  Resolved: 'border-success/40 bg-success/10 text-success',
  Closed: 'border-border bg-muted text-muted-foreground',
}

export function PortalStatus({ label, className }: { label: string; className?: string }) {
  const Icon = label === 'Waiting for your reply' ? MessageCircleQuestion : label === 'Resolved' || label === 'Closed' ? CheckCircle2 : Clock
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium', TONE[label] ?? 'border-primary/30 bg-primary/5 text-primary', className)}>
      <Icon className="size-3" aria-hidden /> {label}
    </span>
  )
}

/** Five-star picker; a radio group so it works with the keyboard and screen readers. */
export function StarRating({ value, onChange, label = 'Rating' }: { value: number; onChange?: (v: number) => void; label?: string }) {
  const [hover, setHover] = useState(0)
  const shown = hover || value
  const words = ['', 'Poor', 'Fair', 'Good', 'Very good', 'Excellent']
  if (!onChange) {
    return (
      <span className="inline-flex items-center gap-0.5" aria-label={`${value} out of 5`}>
        {[1, 2, 3, 4, 5].map((n) => <Star key={n} aria-hidden className={cn('size-4', n <= value ? 'fill-warning text-warning' : 'text-muted-foreground/40')} />)}
      </span>
    )
  }
  return (
    <div role="radiogroup" aria-label={label} className="flex items-center gap-1" onMouseLeave={() => setHover(0)}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} – ${words[n]}`}
          className="rounded p-0.5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          onMouseEnter={() => setHover(n)} onClick={() => onChange(n)}>
          <Star aria-hidden className={cn('size-7 transition-colors', n <= shown ? 'fill-warning text-warning' : 'text-muted-foreground/40')} />
        </button>
      ))}
      <span className="ml-2 text-sm text-muted-foreground" aria-live="polite">{words[shown]}</span>
    </div>
  )
}
