import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { implementedPaths } from '@/app/router'
import { allNavItems } from '@/config/navigation'
import { http, HttpResponse } from 'msw'
import { makeMe, page } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { API, server } from '@/test/server'
import { useThemeStore } from '@/stores/theme'

describe('App shell', () => {
  it('renders navigation, and every module in it is implemented (no "ships in Phase N" placeholders left)', async () => {
    renderRoute('/system', { user: makeMe() })
    expect(screen.getAllByRole('link', { name: /analytics/i }).length).toBeGreaterThan(0)
    expect(allNavItems.map((i) => i.to).filter((to) => !implementedPaths.includes(to))).toEqual([])
  })

  it('hides staff screens from customers and lands them on their requests', async () => {
    server.use(http.get(`${API}/portal/tickets/`, () => HttpResponse.json(page([]))))
    renderRoute('/', { user: makeMe('customer') })
    const nav = await screen.findByRole('navigation', { name: /main/i })
    expect(within(nav).getByRole('link', { name: 'My requests' })).toBeInTheDocument()
    for (const staff of ['Dashboard', 'Tickets', 'System status']) {
      expect(within(nav).queryByRole('link', { name: staff })).not.toBeInTheDocument()
    }
    expect((await screen.findAllByText('New request', {}, { timeout: 3000 })).length).toBeGreaterThan(0)
  })

  it('collapses and expands the sidebar, persisting the choice', async () => {
    const user = userEvent.setup()
    renderRoute('/system', { user: makeMe() })
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false')
    expect(JSON.parse(localStorage.getItem('att.ui')!).state.sidebarCollapsed).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('shows a 404 page for unknown routes', async () => {
    renderRoute('/definitely-not-a-page', { user: makeMe() })
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
  })
})

describe('theme store', () => {
  it('applies the dark class and persists the preference', () => {
    useThemeStore.getState().setPreference('dark')
    expect(document.documentElement).toHaveClass('dark')
    expect(JSON.parse(localStorage.getItem('att.theme')!).state.preference).toBe('dark')
    useThemeStore.getState().setPreference('light')
    expect(document.documentElement).not.toHaveClass('dark')
  })
})
