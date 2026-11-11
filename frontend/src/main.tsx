import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { AppProviders } from '@/app/providers'
import { createRouter } from '@/app/router'
import { createQueryClient } from '@/lib/api/query-client'
import { useThemeStore } from '@/stores/theme'
import './index.css'

// Apply the persisted theme before first paint and follow OS changes in "system" mode.
useThemeStore.persist.rehydrate()
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  const { preference, setPreference } = useThemeStore.getState()
  if (preference === 'system') setPreference('system')
})

const queryClient = createQueryClient()
const router = createRouter()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProviders client={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>
  </StrictMode>,
)
