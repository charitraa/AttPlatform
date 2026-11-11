import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderRoute } from '@/test/render'
import { useThemeStore } from '@/stores/theme'

describe('App shell', () => {
  it('renders navigation and an honest placeholder for unbuilt modules', async () => {
    renderRoute('/tickets')
    expect(screen.getAllByRole('link', { name: /tickets/i }).length).toBeGreaterThan(0)
    expect(await screen.findByText('Tickets ships in Phase 3')).toBeInTheDocument()
  })

  it('collapses and expands the sidebar, persisting the choice', async () => {
    const user = userEvent.setup()
    renderRoute('/system')
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false')
    expect(JSON.parse(localStorage.getItem('att.ui')!).state.sidebarCollapsed).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('shows a 404 page for unknown routes', async () => {
    renderRoute('/definitely-not-a-page')
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
