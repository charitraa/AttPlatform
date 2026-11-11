import { z } from 'zod'

export const paginated = <T extends z.ZodType>(item: T) =>
  z.object({ count: z.number(), next: z.string().nullable(), previous: z.string().nullable(), results: z.array(item) })

export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] }

export function toQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  const s = q.toString()
  return s ? `?${s}` : ''
}
