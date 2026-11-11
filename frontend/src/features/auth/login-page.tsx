import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import type { z } from 'zod'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError } from '@/lib/api/client'
import { useAuthStore } from '@/stores/auth'
import { authApi } from './api'
import { AuthLayout } from './auth-layout'
import { loginSchema } from './schemas'
import { safeNextPath } from './safe-next'

type Values = z.infer<typeof loginSchema>

export function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const setSession = useAuthStore((s) => s.setSession)
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })

  const onSubmit = async (values: Values) => {
    setFormError(null)
    try {
      const session = await authApi.login(values.email, values.password)
      setSession(session.access, session.user)
      navigate(safeNextPath(params.get('next')), { replace: true })
    } catch (error) {
      setFormError(
        error instanceof ApiError && error.code === 'throttled'
          ? 'Too many sign-in attempts. Please wait a minute and try again.'
          : error instanceof ApiError && error.status === 401
            ? 'Incorrect email or password.'
            : error instanceof Error ? error.message : 'Sign-in failed.',
      )
    }
  }

  return (
    <AuthLayout title="Sign in" description="Use your work email to access ATT.">
      <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4" noValidate>
        <FormError message={formError} />
        <Field label="Email" error={errors.email?.message}>
          <Input type="email" autoComplete="email" autoFocus {...register('email')} />
        </Field>
        <Field label="Password" error={errors.password?.message}>
          <Input type="password" autoComplete="current-password" {...register('password')} />
        </Field>
        <div className="-mt-1 text-right">
          <Link to="/forgot-password" className="text-xs text-muted-foreground hover:text-foreground hover:underline">
            Forgot password?
          </Link>
        </div>
        <Button type="submit" size="lg" disabled={isSubmitting}>{isSubmitting ? 'Signing in…' : 'Sign in'}</Button>
      </form>
    </AuthLayout>
  )
}
