const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })
const dateTimeFmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const relFmt = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

export const formatDate = (iso: string | null | undefined) => (iso ? dateFmt.format(new Date(iso)) : '—')
export const formatDateTime = (iso: string | null | undefined) => (iso ? dateTimeFmt.format(new Date(iso)) : '—')

export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'Never'
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const units: [Intl.RelativeTimeFormatUnit, number][] = [['year', 31536000], ['month', 2592000], ['day', 86400], ['hour', 3600], ['minute', 60]]
  for (const [unit, size] of units) if (Math.abs(seconds) >= size) return relFmt.format(Math.round(seconds / size), unit)
  return 'just now'
}
