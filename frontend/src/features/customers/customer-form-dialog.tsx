import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { applyServerErrors } from '@/lib/forms'
import { type Customer, useSaveCustomer } from './api'

const schema = z.object({
  name: z.string().trim().min(2, 'Use at least 2 characters.').max(200),
  type: z.enum(['business', 'individual']),
  tier: z.enum(['standard', 'premium', 'enterprise']),
  email: z.union([z.literal(''), z.email('Enter a valid email address.')]),
  phone: z.string().max(32),
  address_line1: z.string().max(200),
  city: z.string().max(100),
  country: z.string().max(2),
  notes: z.string().max(5000),
})
type Values = z.infer<typeof schema>
const FIELDS = ['name', 'type', 'tier', 'email', 'phone', 'address_line1', 'city', 'country', 'notes'] as const

export function CustomerFormDialog({ customer, open, onClose, onSaved }: {
  customer?: Customer; open: boolean; onClose: () => void; onSaved?: (c: Customer) => void
}) {
  const save = useSaveCustomer(customer?.id)
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: customer?.name ?? '', type: customer?.type ?? 'business', tier: customer?.tier ?? 'standard',
      email: customer?.email ?? '', phone: customer?.phone ?? '', address_line1: customer?.address_line1 ?? '',
      city: customer?.city ?? '', country: customer?.country ?? '', notes: customer?.notes ?? '',
    },
  })

  const onSubmit = async (values: Values) => {
    setFormError(null)
    try {
      const saved = await save.mutateAsync(values)
      toast.success(customer ? 'Customer updated' : `${saved.name} added`)
      onSaved?.(saved)
      onClose()
    } catch (error) {
      setFormError(applyServerErrors(error, setError, FIELDS))
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader><DialogTitle>{customer ? `Edit ${customer.name}` : 'Add customer'}</DialogTitle></DialogHeader>
        <form id="customer-form" onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-4">
          <FormError message={formError} />
          <Field label="Name" error={errors.name?.message}><Input autoFocus {...register('name')} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Type"><NativeSelect {...register('type')}><option value="business">Business</option><option value="individual">Individual</option></NativeSelect></Field>
            <Field label="Tier"><NativeSelect {...register('tier')}><option value="standard">Standard</option><option value="premium">Premium</option><option value="enterprise">Enterprise</option></NativeSelect></Field>
            <Field label="Email" error={errors.email?.message}><Input type="email" {...register('email')} /></Field>
            <Field label="Phone" error={errors.phone?.message}><Input type="tel" {...register('phone')} /></Field>
            <Field label="Address" error={errors.address_line1?.message}><Input {...register('address_line1')} /></Field>
            <div className="grid grid-cols-[1fr_5rem] gap-2">
              <Field label="City" error={errors.city?.message}><Input {...register('city')} /></Field>
              <Field label="Country" error={errors.country?.message}><Input maxLength={2} placeholder="NP" {...register('country')} /></Field>
            </div>
          </div>
          <Field label="Notes"><Textarea rows={3} {...register('notes')} /></Field>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="customer-form" disabled={isSubmitting}>{isSubmitting ? 'Saving…' : customer ? 'Save changes' : 'Add customer'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
