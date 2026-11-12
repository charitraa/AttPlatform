import { Check, Copy, KeyRound } from 'lucide-react'
import { useState } from 'react'
import { Field } from '@/components/forms/field'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { ConnectorField } from './api'

export function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-center gap-2">
      <Input readOnly value={value} aria-label={label} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
      <Button type="button" variant="outline" size="icon" aria-label={`Copy ${label}`}
        onClick={async () => { await navigator.clipboard?.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
        {copied ? <Check /> : <Copy />}
      </Button>
    </div>
  )
}

/** A secret the server generated: shown exactly once. */
export function SecretOnceDialog({ title, secret, onClose }: { title: string; secret: string; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><KeyRound className="size-4" /> {title}</DialogTitle>
          <DialogDescription>Copy it now and store it somewhere safe. For security it won't be shown again — if you lose it, rotate it.</DialogDescription>
        </DialogHeader>
        <CopyField value={secret} label="signing secret" />
        <DialogFooter><Button onClick={onClose}>I've saved it</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Inputs for a connector's settings or secrets. Secrets are password inputs; empty means "unchanged". */
export function ConnectorFields({ fields, values, onChange, errors = {}, secret = false, configured = {} }: {
  fields: ConnectorField[]; values: Record<string, string>; onChange: (name: string, value: string) => void
  errors?: Record<string, string>; secret?: boolean; configured?: Record<string, { configured: boolean; hint: string }>
}) {
  return (
    <>
      {fields.map((f) => {
        const isSet = configured[f.name]?.configured
        const description = secret && isSet ? `Saved (${configured[f.name].hint}). Leave empty to keep it.` : f.help || undefined
        return (
          <Field key={f.name} label={`${f.label}${f.required && !isSet ? '' : ' (optional)'}`} error={errors[f.name]} description={description}>
            {f.kind === 'choice' ? (
              <NativeSelect value={values[f.name] ?? ''} onChange={(e) => onChange(f.name, e.target.value)}>
                <option value="">Default</option>
                {f.choices.map((c) => <option key={c} value={c}>{c}</option>)}
              </NativeSelect>
            ) : (
              <Input type={secret ? 'password' : f.kind === 'url' ? 'url' : 'text'} autoComplete={secret ? 'new-password' : 'off'}
                className={cn(secret && 'font-mono')} value={values[f.name] ?? ''} placeholder={secret && isSet ? '••••••••' : undefined}
                onChange={(e) => onChange(f.name, e.target.value)} />
            )}
          </Field>
        )
      })}
    </>
  )
}

export function HealthDot({ health }: { health: 'unknown' | 'ok' | 'error' }) {
  const label = { ok: 'Working', error: 'Failing', unknown: 'Not used yet' }[health]
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span aria-hidden className={cn('size-2 rounded-full', health === 'ok' ? 'bg-success' : health === 'error' ? 'bg-destructive' : 'bg-muted-foreground/40')} />
      {label}
    </span>
  )
}
