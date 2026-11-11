import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { server } from './server'

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
Object.defineProperty(globalThis, 'WebSocket', { writable: true, value: FakeWebSocket })

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  localStorage.clear()
  useAuthStore.setState({ status: 'idle', accessToken: null, user: null })
})
afterAll(() => server.close())
