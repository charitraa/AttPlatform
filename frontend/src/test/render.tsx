import { QueryClient } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { AppProviders } from '@/app/providers'
import { routes } from '@/app/router'
import type { Me } from '@/features/auth/api'
import { useAuthStore } from '@/stores/auth'
import { makeMe } from './fixtures'

/** Put the auth store into a signed-in state (as if bootstrap had succeeded). */
export function signIn(user: Me = makeMe()) {
  useAuthStore.setState({ status: 'authenticated', accessToken: 'test-access-token', user })
  return user
}

export function renderRoute(path: string, { user }: { user?: Me | null } = {}) {
  if (user) signIn(user)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return { client, router, ...render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>) }
}
