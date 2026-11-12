import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { PageHeader } from '@/components/common/page-header'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { authApi, type Me } from '@/features/auth/api'
import { changePasswordSchema, MIN_PASSWORD } from '@/features/auth/schemas'
import { formatDateTime } from '@/lib/format'
import { applyServerErrors } from '@/lib/forms'
import { timezoneOptions } from '@/lib/timezones'
import { useAuthStore } from '@/stores/auth'

const profileSchema = z.object({
  first_name: z.string().trim().min(1, 'Enter your first name.').max(150),
  last_name: z.string().trim().max(150),
  phone: z.string().trim().max(32).regex(/^[+\d\s()-]*$/, 'Use digits, spaces and + ( ) - only.'),
  timezone: z.string().min(1),
})
type ProfileValues = z.infer<typeof profileSchema>
type PasswordValues = z.infer<typeof changePasswordSchema>

function ProfileForm({ user }: { user: Me }) {
  const setUser = useAuthStore((s) => s.setUser)
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, reset, formState: { errors, isSubmitting, isDirty } } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: { first_name: user.first_name, last_name: user.last_name, phone: user.phone, timezone: user.timezone },
  })

  const onSubmit = async (values: ProfileValues) => {
    setFormError(null)
    try {
      const updated = await authApi.updateMe(values)
      setUser(updated)
      reset(values)
      toast.success('Profile updated')
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ['first_name', 'last_name', 'phone', 'timezone']))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Personal information</CardTitle>
        <CardDescription>Your name and contact details as other members see them.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
          <FormError message={formError} />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First name" error={errors.first_name?.message}><Input autoComplete="given-name" {...register('first_name')} /></Field>
            <Field label="Last name" error={errors.last_name?.message}><Input autoComplete="family-name" {...register('last_name')} /></Field>
            <Field label="Email" description="Contact an administrator to change your sign-in email.">
              <Input value={user.email} readOnly disabled />
            </Field>
            <Field label="Phone" error={errors.phone?.message} description="International format, e.g. +977 9847206256. Used for WhatsApp notifications if you turn them on."><Input type="tel" autoComplete="tel" {...register('phone')} /></Field>
            <Field label="Timezone" error={errors.timezone?.message} description="Used to display dates and times.">
              <NativeSelect {...register('timezone')}>
                {timezoneOptions(user.timezone).map((tz) => <option key={tz} value={tz}>{tz}</option>)}
              </NativeSelect>
            </Field>
          </div>
          <div className="flex justify-end">
            <Button type="submit" disabled={isSubmitting || !isDirty}>{isSubmitting ? 'Saving…' : 'Save changes'}</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function PasswordForm() {
  const setAccessToken = useAuthStore((s) => s.setAccessToken)
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, reset, formState: { errors, isSubmitting } } = useForm<PasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: '', new_password: '', confirm: '' },
  })

  const onSubmit = async ({ current_password, new_password }: PasswordValues) => {
    setFormError(null)
    try {
      const { access } = await authApi.changePassword({ current_password, new_password })
      setAccessToken(access)
      reset()
      toast.success('Password changed. Other devices have been signed out.')
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ['current_password', 'new_password']))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Password</CardTitle>
        <CardDescription>Changing your password signs you out on every other device.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 sm:max-w-sm" noValidate>
          <FormError message={formError} />
          <Field label="Current password" error={errors.current_password?.message}>
            <Input type="password" autoComplete="current-password" {...register('current_password')} />
          </Field>
          <Field label="New password" error={errors.new_password?.message} description={`At least ${MIN_PASSWORD} characters.`}>
            <Input type="password" autoComplete="new-password" {...register('new_password')} />
          </Field>
          <Field label="Confirm new password" error={errors.confirm?.message}>
            <Input type="password" autoComplete="new-password" {...register('confirm')} />
          </Field>
          <div><Button type="submit" disabled={isSubmitting}>{isSubmitting ? 'Updating…' : 'Update password'}</Button></div>
        </form>
      </CardContent>
    </Card>
  )
}

export function ProfileSettingsPage() {
  const user = useAuthStore((s) => s.user)
  if (!user) return null
  return (
    <div className="space-y-6">
      <PageHeader title="Profile settings" description={`${user.role.name} at ${user.organization.name} · last sign-in ${formatDateTime(user.last_login)}`} />
      <div className="grid gap-6 lg:grid-cols-[2fr_1fr] lg:items-start">
        <ProfileForm user={user} />
        <PasswordForm />
      </div>
    </div>
  )
}
