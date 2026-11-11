import { z } from 'zod'

// Mirrors the backend's minimum; the server remains authoritative (common-password checks etc.).
export const MIN_PASSWORD = 10

export const newPassword = z
  .string()
  .min(MIN_PASSWORD, `Use at least ${MIN_PASSWORD} characters.`)
  .max(128, 'Use at most 128 characters.')
  .refine((v) => !/^\d+$/.test(v), 'Password cannot be entirely numeric.')

export const loginSchema = z.object({
  email: z.email('Enter a valid email address.'),
  password: z.string().min(1, 'Enter your password.'),
})

export const forgotPasswordSchema = z.object({ email: z.email('Enter a valid email address.') })

export const resetPasswordSchema = z
  .object({ new_password: newPassword, confirm: z.string() })
  .refine((d) => d.new_password === d.confirm, { path: ['confirm'], message: 'Passwords do not match.' })

export const changePasswordSchema = z
  .object({ current_password: z.string().min(1, 'Enter your current password.'), new_password: newPassword, confirm: z.string() })
  .refine((d) => d.new_password === d.confirm, { path: ['confirm'], message: 'Passwords do not match.' })
