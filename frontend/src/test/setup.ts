import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { server } from './server'

// Routes are lazy-loaded chunks (charts etc.); a cold import under full-suite load can exceed the 1 s default.
configure({ asyncUtilTimeout: 3000 })

// jsdom lacks matchMedia and WebSocket; provide minimal, inert versions.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
    dispatchEvent: () => false,
  }),
})

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
    queueMicrotask(() => this.onopen?.())
  }
  send() {}
  close() {}
}
beforeAll(() => {
  server.listen({ onUnhandledFrame: 'error' })
  // Install after listen(): MSW patches WebSocket for interception; app sockets stay inert in tests.
  // (Tests that drive the event stream swap in their own fake with vi.stubGlobal.)
  Object.defineProperty(globalThis, 'WebSocket', { writable: true, configurable: true, value: FakeWebSocket })
})
afterEach(() => {
  cleanup()
  server.resetHandlers()
  localStorage.clear()
  useAuthStore.setState({ status: 'idle', accessToken: null, user: null })
})
afterAll(() => server.close())
