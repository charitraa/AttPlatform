import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import type { z } from 'zod'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { applyServerErrors } from '@/lib/forms'
import { authApi } from './api'
import { AuthLayout } from './auth-layout'
import { MIN_PASSWORD, resetPasswordSchema } from './schemas'

type Values = z.infer<typeof resetPasswordSchema>

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const uid = params.get('uid') ?? ''
  const token = params.get('token') ?? ''
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: '', confirm: '' },
  })

  const footer = <Link to="/login" className="hover:text-foreground hover:underline">Back to sign in</Link>

  if (!uid || !token) {
    return (
      <AuthLayout title="Invalid reset link" footer={footer}>
        <p className="text-sm text-muted-foreground">
          This link is incomplete. <Link to="/forgot-password" className="text-primary hover:underline">Request a new one</Link>.
        </p>
      </AuthLayout>
    )
  }

  const onSubmit = async (values: Values) => {
    setFormError(null)
    try {
      await authApi.resetPassword({ uid, token, new_password: values.new_password })
      toast.success('Password updated. Sign in with your new password.')
      navigate('/login', { replace: true })
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ['new_password']))
    }
  }

  return (
    <AuthLayout title="Choose a new password" footer={footer}>
      <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
        <FormError message={formError} />
        <Field label="New password" error={errors.new_password?.message} description={`At least ${MIN_PASSWORD} characters.`}>
          <Input type="password" autoComplete="new-password" autoFocus {...register('new_password')} />
        </Field>
        <Field label="Confirm new password" error={errors.confirm?.message}>
          <Input type="password" autoComplete="new-password" {...register('confirm')} />
        </Field>
        <Button type="submit" size="lg" disabled={isSubmitting}>{isSubmitting ? 'Saving…' : 'Set new password'}</Button>
      </form>
    </AuthLayout>
  )
}
