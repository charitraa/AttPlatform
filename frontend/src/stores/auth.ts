import { create } from 'zustand'
import { authApi, type Me } from '@/features/auth/api'
import { ApiError, setAccessTokenProvider, setTokenRefresher } from '@/lib/api/client'

export type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'anonymous'

interface AuthState {
  status: AuthStatus
  /** Short-lived access token. Memory only: never persisted to storage. */
  accessToken: string | null
  user: Me | null
  /** Restore a session from the HttpOnly refresh cookie on app start. */
  bootstrap: () => Promise<void>
  setSession: (accessToken: string, user: Me) => void
  setUser: (user: Me) => void
  setAccessToken: (accessToken: string) => void
  logout: () => Promise<void>
  /** Local sign-out without calling the API (session already invalid). */
  clear: () => void
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  status: 'idle',
  accessToken: null,
  user: null,

  bootstrap: async () => {
    if (get().status === 'loading') return
    set({ status: 'loading' })
    try {
      const { access } = await authApi.refresh()
      set({ accessToken: access })
      const user = await authApi.me()
      set({ user, status: 'authenticated' })
    } catch {
      set({ accessToken: null, user: null, status: 'anonymous' })
    }
  },

  setSession: (accessToken, user) => set({ accessToken, user, status: 'authenticated' }),
  setUser: (user) => set({ user }),
  setAccessToken: (accessToken) => set({ accessToken }),

  logout: async () => {
    try {
      await authApi.logout()
    } finally {
      get().clear()
    }
  },

  clear: () => set({ accessToken: null, user: null, status: 'anonymous' }),
}))

// Wire the API client to the store: attach tokens, and transparently refresh them.
setAccessTokenProvider(() => useAuthStore.getState().accessToken)
setTokenRefresher(async () => {
  try {
    const { access } = await authApi.refresh()
    useAuthStore.getState().setAccessToken(access)
    return access
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) useAuthStore.getState().clear()
    return null
  }
})

export function hasPermission(user: Me | null, ...codes: string[]): boolean {
  return !!user && codes.every((c) => user.permissions.includes(c))
}

export function hasAnyPermission(user: Me | null, codes: string[]): boolean {
  return !!user && (codes.length === 0 || codes.some((c) => user.permissions.includes(c)))
}

export function useCan(...codes: string[]): boolean {
  return useAuthStore((s) => hasPermission(s.user, ...codes))
}
