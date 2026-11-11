import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'
import { PageHeader } from '@/components/common/page-header'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useAssets } from '@/features/assets/api'
import { useContacts, useCustomers } from '@/features/customers/api'
import { applyServerErrors } from '@/lib/forms'
import { useCan } from '@/stores/auth'
import { useCategories, useCreateTicket } from './api'
import { CHANNELS, CHANNEL_LABEL, PRIORITIES, PRIORITY_LABEL } from './constants'

const schema = z.object({
  title: z.string().trim().min(5, 'Use at least 5 characters so the issue is recognisable.').max(200),
  description: z.string().trim().min(10, 'Describe the issue in a little more detail.').max(20000),
  customer: z.string(),
  contact: z.string(),
  asset: z.string(),
  category: z.string(),
  priority: z.string(),
  channel: z.string(),
  tags: z.string().max(400),
})
type Values = z.infer<typeof schema>

export function CreateTicketPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // Customer-portal users don't pick a customer; the API uses their own account.
  const isStaff = useCan('customers.view')
  const create = useCreateTicket()
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, watch, setValue, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema.superRefine((v, ctx) => {
      if (isStaff && !v.customer) ctx.addIssue({ code: 'custom', path: ['customer'], message: 'Choose a customer.' })
    })),
    defaultValues: {
      title: '', description: '', customer: params.get('customer') ?? '', contact: '', asset: params.get('asset') ?? '',
      category: '', priority: '', channel: 'phone', tags: '',
    },
  })
  const customerId = watch('customer')
  const categoryId = watch('category')

  const customers = useCustomers({ page_size: 100, ordering: 'name' }, isStaff)
  const contacts = useContacts(isStaff && customerId ? customerId : undefined)
  const assets = useAssets({ customer: customerId, page_size: 100 }, isStaff && !!customerId)
  const categories = useCategories()
  const defaultPriority = categories.data?.find((c) => c.id === categoryId)?.default_priority

  const onSubmit = async (v: Values) => {
    setFormError(null)
    try {
      const ticket = await create.mutateAsync({
        title: v.title,
        description: v.description,
        ...(isStaff && {
          customer: v.customer,
          contact: v.contact || null,
          asset: v.asset || null,
          ...(v.priority && { priority: v.priority }),
          channel: v.channel,
        }),
        category: v.category || null,
        tags: v.tags.split(',').map((t) => t.trim()).filter(Boolean),
      } as Parameters<typeof create.mutateAsync>[0])
      toast.success(`${ticket.reference} created`)
      navigate(`/tickets/${ticket.id}`)
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ['title', 'description', 'customer', 'contact', 'asset', 'category', 'priority', 'channel']))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="New ticket" description={isStaff ? 'Log a request on behalf of a customer.' : 'Tell us what went wrong and we will get back to you.'} />
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-6 lg:grid-cols-[2fr_1fr] lg:items-start">
        <Card>
          <CardHeader>
            <CardTitle>Issue</CardTitle>
            <CardDescription>A clear title and the steps to reproduce help us resolve it faster.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <FormError message={formError} />
            <Field label="Title" error={errors.title?.message}>
              <Input autoFocus placeholder="e.g. Server room AC not cooling" {...register('title')} />
            </Field>
            <Field label="Description" error={errors.description?.message}
              description="What happened, when it started, and anything you've already tried.">
              <Textarea rows={8} {...register('description')} />
            </Field>
            <Field label="Category" error={errors.category?.message}
              description={defaultPriority && isStaff ? `Default priority for this category: ${PRIORITY_LABEL[defaultPriority]}` : undefined}>
              <NativeSelect {...register('category')}>
                <option value="">Not sure</option>
                {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}
              </NativeSelect>
            </Field>
            {isStaff && (
              <Field label="Tags" error={errors.tags?.message} description="Comma-separated, e.g. vip, onsite">
                <Input {...register('tags')} />
              </Field>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-6">
          {isStaff && (
            <Card>
              <CardHeader><CardTitle>Customer</CardTitle></CardHeader>
              <CardContent className="grid gap-4">
                <Field label="Customer" error={errors.customer?.message}
                  description={customers.data && customers.data.count > 100 ? 'Showing the first 100 customers alphabetically.' : undefined}>
                  <NativeSelect {...register('customer', { onChange: () => { setValue('contact', ''); setValue('asset', '') } })}>
                    <option value="">{customers.isPending ? 'Loading…' : 'Choose a customer'}</option>
                    {customers.data?.results.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </NativeSelect>
                </Field>
                <Field label="Contact" error={errors.contact?.message}>
                  <NativeSelect disabled={!customerId} {...register('contact')}>
                    <option value="">{customerId ? 'No specific contact' : 'Choose a customer first'}</option>
                    {contacts.data?.map((c) => <option key={c.id} value={c.id}>{c.name}{c.is_primary ? ' (primary)' : ''}</option>)}
                  </NativeSelect>
                </Field>
                <Field label="Asset" error={errors.asset?.message}>
                  <NativeSelect disabled={!customerId} {...register('asset')}>
                    <option value="">{customerId ? 'No asset' : 'Choose a customer first'}</option>
                    {assets.data?.results.map((a) => <option key={a.id} value={a.id}>{a.asset_tag} · {a.name}</option>)}
                  </NativeSelect>
                </Field>
              </CardContent>
            </Card>
          )}
          {isStaff && (
            <Card>
              <CardHeader><CardTitle>Triage</CardTitle></CardHeader>
              <CardContent className="grid gap-4">
                <Field label="Priority" error={errors.priority?.message}>
                  <NativeSelect {...register('priority')}>
                    <option value="">{defaultPriority ? `Category default (${PRIORITY_LABEL[defaultPriority]})` : 'Default (Medium)'}</option>
                    {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
                  </NativeSelect>
                </Field>
                <Field label="Received via" error={errors.channel?.message}>
                  <NativeSelect {...register('channel')}>
                    {CHANNELS.map((c) => <option key={c} value={c}>{CHANNEL_LABEL[c]}</option>)}
                  </NativeSelect>
                </Field>
              </CardContent>
            </Card>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" nativeButton={false} render={<Link to="/tickets" />}>Cancel</Button>
            <Button type="submit" disabled={isSubmitting}>{isSubmitting ? 'Creating…' : 'Create ticket'}</Button>
          </div>
        </div>
      </form>
    </div>
  )
}
