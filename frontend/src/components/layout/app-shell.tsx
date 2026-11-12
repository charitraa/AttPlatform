import { Outlet } from 'react-router-dom'
import { useEventStream } from '@/lib/realtime/events'
import { Sidebar } from './sidebar'
import { Topbar } from './topbar'

export function AppShell() {
  useEventStream()
  return (
    <div className="flex min-h-svh bg-background">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-background focus:px-3 focus:py-2">
        Skip to content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
