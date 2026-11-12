import { useEffect, useState } from 'react'
import { reportLocation } from './api'

export type ReporterState = 'off' | 'waiting' | 'sharing' | 'denied' | 'unavailable'

const supported = () => typeof navigator !== 'undefined' && 'geolocation' in navigator

/**
 * Sends the technician's position while `active` (sharing opted in and a job is en route / on site /
 * in progress), at most once per `intervalMs`. The browser asks for permission on first use; a
 * refusal is reported back rather than retried. Rejections from the API (409 when the job has just
 * ended or sharing was switched off elsewhere) are ignored: the next status change stops the watcher.
 */
export function useLocationReporter(active: boolean, intervalMs = 60_000): ReporterState {
  const [state, setState] = useState<Exclude<ReporterState, 'off'>>('waiting')

  useEffect(() => {
    if (!active || !supported()) return
    let last = 0
    const watchId = navigator.geolocation.watchPosition(
      (p) => {
        const now = Date.now()
        if (now - last < intervalMs) return
        last = now
        setState('sharing')
        reportLocation({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy_m: p.coords.accuracy }).catch(() => undefined)
      },
      (err) => setState(err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable'),
      { enableHighAccuracy: true, maximumAge: 30_000, timeout: 30_000 },
    )
    return () => {
      navigator.geolocation.clearWatch(watchId)
      setState('waiting')
    }
  }, [active, intervalMs])

  if (!active) return 'off'
  if (!supported()) return 'unavailable'
  return state
}
