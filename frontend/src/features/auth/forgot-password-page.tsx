import { zodResolver } from '@hookform/resolvers/zod'
import { MailCheck } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import type { z } from 'zod'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { authApi } from './api'
import { AuthLayout } from './auth-layout'
import { forgotPasswordSchema } from './schemas'

type Values = z.infer<typeof forgotPasswordSchema>

export function ForgotPasswordPage() {
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: '' },
  })

  const onSubmit = async ({ email }: Values) => {
    setFormError(null)
    try {
      await authApi.forgotPassword(email)
      setSentTo(email)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Request failed.')
    }
  }

  const footer = <Link to="/login" className="hover:text-foreground hover:underline">Back to sign in</Link>

  if (sentTo) {
    return (
      <AuthLayout title="Check your email" footer={footer}>
        <div className="flex flex-col items-center gap-3 text-center">
          <MailCheck className="size-8 text-primary" aria-hidden />
          <p className="text-sm text-muted-foreground">
            If an account exists for <span className="font-medium text-foreground">{sentTo}</span>, we've sent a link
            to reset your password. It expires in 60 minutes.
          </p>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Reset your password" description="Enter your email and we'll send you a reset link." footer={footer}>
      <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
        <FormError message={formError} />
        <Field label="Email" error={errors.email?.message}>
          <Input type="email" autoComplete="email" autoFocus {...register('email')} />
        </Field>
        <Button type="submit" size="lg" disabled={isSubmitting}>{isSubmitting ? 'Sending…' : 'Send reset link'}</Button>
      </form>
    </AuthLayout>
  )
}
