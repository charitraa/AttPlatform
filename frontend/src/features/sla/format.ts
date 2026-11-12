/** "2h 05m", "3d 4h", "45m" — compact durations for SLA clocks. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.abs(Math.round(totalSeconds))
  const d = Math.floor(s / 86_400), h = Math.floor((s % 86_400) / 3600), m = Math.floor((s % 3600) / 60)
  if (d) return `${d}d ${h}h`
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`
  return `${Math.max(m, s > 0 ? 1 : 0)}m`
}

export function minutesLabel(minutes: number): string {
  return formatDuration(minutes * 60)
}
