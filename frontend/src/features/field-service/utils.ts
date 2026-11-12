import type { Health } from '@/components/common/status-indicator'
import type { Technician, WorkOrder } from './api'

export const TECH_HEALTH: Record<Technician['status'], Health> = {
  available: 'ok', busy: 'warning', off_duty: 'unknown', on_leave: 'unknown',
}

/** OpenStreetMap link for a job site (coordinates when known, else an address search). */
export function mapsUrl(wo: Pick<WorkOrder, 'lat' | 'lng' | 'service_address'>): string | null {
  if (wo.lat && wo.lng) return `https://www.openstreetmap.org/?mlat=${wo.lat}&mlon=${wo.lng}#map=16/${wo.lat}/${wo.lng}`
  if (wo.service_address) return `https://www.openstreetmap.org/search?query=${encodeURIComponent(wo.service_address)}`
  return null
}

/** Monday 00:00 local time of the week containing `d`. */
export function startOfWeek(d: Date): Date {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7))
  return x
}

export function addDays(d: Date, n: number): Date {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

export const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
