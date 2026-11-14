import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeMe } from '@/test/fixtures'
import { renderRoute } from '@/test/render'

describe('landing page', () => {
  it('is what signed-out visitors see at /', async () => {
    const { router } = renderRoute('/')
    expect(await screen.findByRole('heading', { level: 1, name: /every job, from the first message/i })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/welcome')
    expect(screen.getAllByRole('link', { name: 'Sign in' })[0]).toHaveAttribute('href', '/login')
    expect(screen.getByRole('figure', { name: /example work order/i })).toBeInTheDocument()
    // No contact address configured in tests: no dead "Request a demo" button.
    expect(screen.queryByRole('link', { name: 'Request a demo' })).not.toBeInTheDocument()
  })

  it('keeps signed-in people in the app', async () => {
    const { router } = renderRoute('/welcome', { user: makeMe() })
    await screen.findByRole('navigation', { name: /main/i })
    expect(router.state.location.pathname).not.toBe('/welcome')
  })

  it('sends deep links to sign-in, not to the landing page', async () => {
    const { router } = renderRoute('/tickets')
    await screen.findByRole('button', { name: /sign in/i })
    expect(router.state.location.pathname).toBe('/login')
  })
})
