import { ArrowLeft } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api/client'
import { firstErrorMessage } from '@/lib/forms'
import { usePortalMutations, usePortalOptions } from './api'

export function PortalNewTicketPage() {
  const navigate = useNavigate()
  const options = usePortalOptions()
  const { create } = usePortalMutations()
  const [form, setForm] = useState({ title: '', description: '', category: '', asset: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!form.title.trim()) local.title = 'Give your request a short title.'
    if (form.description.trim().length < 10) local.description = 'Describe the problem in a sentence or two.'
    setErrors(local)
    if (Object.keys(local).length) return
    setError(null)
    try {
      const t = await create.mutateAsync({ title: form.title.trim(), description: form.description.trim(),
        category: form.category || null, asset: form.asset || null })
      toast.success(`Request ${t.reference} sent`)
      navigate(`/portal/tickets/${t.id}`, { replace: true })
    } catch (err) {
      const details = err instanceof ApiError && err.details && typeof err.details === 'object' ? err.details as Record<string, string[]> : {}
      setErrors(Object.fromEntries(Object.entries(details).map(([k, v]) => [k, Array.isArray(v) ? v[0] : String(v)])))
      setError(firstErrorMessage(err))
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <Link to="/portal" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Your requests</Link>
      <Card>
        <CardHeader><CardTitle>New request</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4" noValidate>
            <FormError message={error} />
            <Field label="What's the problem?" error={errors.title}>
              <Input value={form.title} maxLength={200} placeholder="e.g. Cold room isn't cooling" onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </Field>
            <Field label="Details" error={errors.description} description="When did it start, what have you tried, how urgent is it?">
              <Textarea rows={6} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Type (optional)" error={errors.category}>
                <NativeSelect value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  <option value="">Not sure</option>
                  {options.data?.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </NativeSelect>
              </Field>
              <Field label="Equipment (optional)" error={errors.asset}>
                <NativeSelect value={form.asset} onChange={(e) => setForm({ ...form, asset: e.target.value })}>
                  <option value="">None / not listed</option>
                  {options.data?.assets.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.asset_tag})</option>)}
                </NativeSelect>
              </Field>
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" render={<Link to="/portal" />} nativeButton={false}>Cancel</Button>
              <Button type="submit" disabled={create.isPending}>Send request</Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
