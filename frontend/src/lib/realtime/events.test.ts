import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { applyStreamMessage } from './events'

describe('applyStreamMessage', () => {
  it('a ticket change refreshes staff and customer portal screens, but not static options', () => {
    const qc = new QueryClient()
    for (const key of [['tickets', 'list'], ['portal', 'tickets', 't-1'], ['portal', 'options'], ['tickets', 'categories']]) {
      qc.setQueryData(key, 'x')
    }
    applyStreamMessage(qc, { type: 'ticket.changed', ticket_id: 't-1', change: 'ticket.commented' })
    const stale = (key: string[]) => qc.getQueryState(key)?.isInvalidated
    expect(stale(['tickets', 'list'])).toBe(true)
    expect(stale(['portal', 'tickets', 't-1'])).toBe(true)
    expect(stale(['portal', 'options'])).toBe(false)
    expect(stale(['tickets', 'categories'])).toBe(false)
  })
})
