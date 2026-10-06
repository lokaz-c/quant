import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// globals are off, so Testing Library can't register its own cleanup
afterEach(() => cleanup())

// jsdom has no ResizeObserver; Recharts' responsive charts need one
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
