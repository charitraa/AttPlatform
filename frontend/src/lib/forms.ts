import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'
import { ApiError } from '@/lib/api/client'

/**
 * Map a backend validation error ({"field": ["msg"]}) onto react-hook-form fields.
 * Returns a message for errors that don't belong to a known field (show it as a
 * form-level error), or null when everything was attached to a field.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly Path<T>[],
): string | null {
  if (!(error instanceof ApiError)) return 'Something went wrong. Please try again.'
  const details = error.details
  if (error.code === 'validation_error' && details && typeof details === 'object' && !Array.isArray(details)) {
    const leftovers: string[] = []
    for (const [key, value] of Object.entries(details as Record<string, unknown>)) {
      const message = Array.isArray(value) ? String(value[0]) : String(value)
      if ((fields as readonly string[]).includes(key)) setError(key as Path<T>, { type: 'server', message })
      else leftovers.push(message)
    }
    return leftovers.length ? leftovers.join(' ') : null
  }
  return error.message
}
