import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { PageHeader } from '@/components/common/page-header'
import { ErrorState } from '@/components/common/states'
import { CheckboxField } from '@/components/forms/checkbox-field'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/format'
import { applyServerErrors } from '@/lib/forms'
import { timezoneOptions } from '@/lib/timezones'
import { useCan } from '@/stores/auth'
import { type Organization, useOrganization, useUpdateOrganization } from './api'

const schema = z.object({
  name: z.string().trim().min(2, 'Use at least 2 characters.').max(200),
  timezone: z.string().min(1),
  locale: z.string().min(2).max(16),
  routing_policy: z.enum(['manual', 'recommend', 'auto']),
  ai_enabled: z.boolean(),
  ticket_auto_close_days: z.number({ error: 'Enter a number.' }).int().min(1, 'Minimum 1 day.').max(90, 'Maximum 90 days.'),
})
type Values = z.infer<typeof schema>

const ROUTING_HELP: Record<Values['routing_policy'], string> = {
  manual: 'Agents assign every ticket themselves. AI makes no routing suggestions.',
  recommend: 'AI suggests an assignee with its reasoning; a person approves it.',
  auto: 'AI assigns automatically when its confidence is high enough; low-confidence cases wait for a person.',
}

function OrganizationForm({ org, canEdit }: { org: Organization; canEdit: boolean }) {
  const update = useUpdateOrganization()
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, reset, watch, formState: { errors, isSubmitting, isDirty } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: org.name, timezone: org.timezone, locale: org.locale, ...org.settings },
  })
  const routing = watch('routing_policy')

  const onSubmit = async ({ routing_policy, ai_enabled, ticket_auto_close_days, ...profile }: Values) => {
    setFormError(null)
    try {
      const saved = await update.mutateAsync({ ...profile, settings: { routing_policy, ai_enabled, ticket_auto_close_days } })
      reset({ name: saved.name, timezone: saved.timezone, locale: saved.locale, ...saved.settings })
      toast.success('Organization settings saved')
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ['name', 'timezone', 'locale']))
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="grid gap-6" noValidate>
      <FormError message={formError} />
      <fieldset disabled={!canEdit} className="grid gap-6 lg:grid-cols-2 lg:items-start">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
            <CardDescription>Identifier: <span className="font-mono">{org.slug}</span> · created {formatDate(org.created_at)}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Field label="Organization name" error={errors.name?.message}><Input {...register('name')} /></Field>
            <Field label="Default timezone" error={errors.timezone?.message} description="Used for business hours and SLA calculations.">
              <NativeSelect {...register('timezone')}>
                {timezoneOptions(org.timezone).map((tz) => <option key={tz} value={tz}>{tz}</option>)}
              </NativeSelect>
            </Field>
            <Field label="Language" error={errors.locale?.message}>
              <NativeSelect {...register('locale')}>
                <option value="en">English</option>
              </NativeSelect>
            </Field>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Operations</CardTitle>
            <CardDescription>How tickets are routed and closed.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Field label="Ticket routing" description={ROUTING_HELP[routing]}>
              <NativeSelect {...register('routing_policy')}>
                <option value="manual">Manual</option>
                <option value="recommend">AI recommends, a person approves</option>
                <option value="auto">AI assigns automatically</option>
              </NativeSelect>
            </Field>
            <CheckboxField label="Enable AI features" description="Classification, priority prediction, summaries and suggestions." {...register('ai_enabled')} />
            <Field label="Auto-close resolved tickets after (days)" error={errors.ticket_auto_close_days?.message}>
              <Input type="number" min={1} max={90} className="w-28" {...register('ticket_auto_close_days', { valueAsNumber: true })} />
            </Field>
          </CardContent>
        </Card>
      </fieldset>
      {canEdit && (
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" disabled={!isDirty || isSubmitting} onClick={() => reset()}>Discard</Button>
          <Button type="submit" disabled={!isDirty || isSubmitting}>{isSubmitting ? 'Saving…' : 'Save settings'}</Button>
        </div>
      )}
    </form>
  )
}

export function OrganizationSettingsPage() {
  const org = useOrganization()
  const canEdit = useCan('organization.manage')
  return (
    <div className="space-y-6">
      <PageHeader
        title="Organization settings"
        description="Organization-wide defaults for every member."
        actions={!canEdit && <Badge variant="outline">Read only</Badge>}
      />
      {org.isPending ? (
        <div className="grid gap-6 lg:grid-cols-2"><Skeleton className="h-72" /><Skeleton className="h-72" /></div>
      ) : org.isError ? (
        <ErrorState error={org.error} onRetry={() => org.refetch()} />
      ) : (
        <OrganizationForm org={org.data} canEdit={canEdit} />
      )}
    </div>
  )
}
