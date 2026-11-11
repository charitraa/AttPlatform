import { afterEach, describe, expect, it, vi } from 'vitest'
import { timezoneOptions } from './timezones'

describe('timezoneOptions', () => {
  afterEach(() => vi.restoreAllMocks())

  it('keeps a saved zone the browser lists under a legacy name', () => {
    vi.spyOn(Intl, 'supportedValuesOf').mockReturnValue(['Asia/Katmandu', 'Europe/London', 'UTC'])
    const options = timezoneOptions('Asia/Kathmandu')
    expect(options[0]).toBe('UTC')
    expect(options).toContain('Asia/Kathmandu')
    expect(options.filter((z) => z === 'UTC')).toHaveLength(1)
  })

  it('does not duplicate zones already listed', () => {
    vi.spyOn(Intl, 'supportedValuesOf').mockReturnValue(['Europe/London'])
    expect(timezoneOptions('Europe/London')).toEqual(['UTC', 'Europe/London'])
  })
})
