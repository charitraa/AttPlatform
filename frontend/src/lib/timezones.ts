/**
 * IANA timezones supported by the browser, UTC first.
 *
 * Browsers list some zones under legacy names (Chromium returns "Asia/Katmandu",
 * "Asia/Calcutta"), while the server may store the modern spelling
 * ("Asia/Kathmandu"). The currently saved value is always included so a <select>
 * never silently shows, or submits, a different zone.
 */
export function timezoneOptions(current?: string): string[] {
  const zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : []
  const options = ['UTC', ...zones.filter((z) => z !== 'UTC')]
  if (current && !options.includes(current)) options.splice(1, 0, current)
  return options
}
