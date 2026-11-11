import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { z } from 'zod'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { applyServerErrors } from '@/lib/forms'
import { useAuthStore } from '@/stores/auth'
import { authApi, type InvitationPreview } from './api'
import { AuthLayout } from './auth-layout'
import { MIN_PASSWORD, newPassword } from './schemas'

const newAccountSchema = z
  .object({
    first_name: z.string().trim().min(1, 'Enter your first name.').max(150),
    last_name: z.string().trim().min(1, 'Enter your last name.').max(150),
    password: newPassword,
    confirm: z.string(),
  })
  .refine((d) => d.password === d.confirm, { path: ['confirm'], message: 'Passwords do not match.' })

const existingAccountSchema = z.object({
  first_name: z.string().optional(),
  last_name: z.string().optional(),
  password: z.string().min(1, 'Enter your current password.'),
  confirm: z.string().optional(),
})

type Values = z.infer<typeof newAccountSchema>

function AcceptForm({ token, preview }: { token: string; preview: InvitationPreview }) {
  const navigate = useNavigate()
  const setSession = useAuthStore((s) => s.setSession)
  const [formError, setFormError] = useState<string | null>(null)
  const existing = preview.existing_account
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver((existing ? existingAccountSchema : newAccountSchema) as typeof newAccountSchema),
    defaultValues: { first_name: '', last_name: '', password: '', confirm: '' },
  })

  const onSubmit = async (values: Values) => {
    setFormError(null)
    try {
      const session = await authApi.acceptInvitation({
        token, password: values.password, first_name: values.first_name, last_name: values.last_name,
      })
      setSession(session.access, session.user)
      navigate('/', { replace: true })
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ['password', 'first_name', 'last_name']))
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <FormError message={formError} />
      <div className="rounded-lg bg-muted px-3 py-2 text-sm">
        Joining <span className="font-medium">{preview.organization_name}</span> as{' '}
        <span className="font-medium">{preview.role_name}</span>
        <div className="text-xs text-muted-foreground">{preview.email}</div>
      </div>
      {existing ? (
        <Field label="Your current password" error={errors.password?.message}
          description="You already have an ATT account. Confirm it's you to join this organization.">
          <Input type="password" autoComplete="current-password" autoFocus {...register('password')} />
        </Field>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name" error={errors.first_name?.message}>
              <Input autoComplete="given-name" autoFocus {...register('first_name')} />
            </Field>
            <Field label="Last name" error={errors.last_name?.message}>
              <Input autoComplete="family-name" {...register('last_name')} />
            </Field>
          </div>
          <Field label="Password" error={errors.password?.message} description={`At least ${MIN_PASSWORD} characters.`}>
            <Input type="password" autoComplete="new-password" {...register('password')} />
          </Field>
          <Field label="Confirm password" error={errors.confirm?.message}>
            <Input type="password" autoComplete="new-password" {...register('confirm')} />
          </Field>
        </>
      )}
      <Button type="submit" size="lg" disabled={isSubmitting}>{isSubmitting ? 'Joining…' : 'Accept invitation'}</Button>
    </form>
  )
}

export function AcceptInvitePage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const preview = useQuery({
    queryKey: ['invitation-preview', token],
    queryFn: () => authApi.previewInvitation(token),
    enabled: !!token,
    retry: false,
  })
  const footer = <Link to="/login" className="hover:text-foreground hover:underline">Back to sign in</Link>

  if (!token || preview.isError) {
    return (
      <AuthLayout title="Invitation unavailable" footer={footer}>
        <p className="text-sm text-muted-foreground">
          This invitation link is invalid, has expired, or was already used. Ask your administrator to send a new one.
        </p>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Accept invitation" footer={footer}>
      {preview.isPending ? (
        <div className="grid gap-3"><Skeleton className="h-12" /><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
      ) : (
        <AcceptForm token={token} preview={preview.data} />
      )}
    </AuthLayout>
  )
}
