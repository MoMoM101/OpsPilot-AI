import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useIncidentEventStream } from './useIncidentEventStream'

const mocks = vi.hoisted(() => ({
  incident: vi.fn(),
  stream: vi.fn(),
}))

vi.mock('./dataApi', () => ({
  dataApi: { mode: 'http', incident: mocks.incident, incidents: vi.fn(), dashboard: vi.fn() },
}))
vi.mock('./sseClient', () => ({
  SseConnectionError: class SseConnectionError extends Error {
    constructor(readonly kind: string, message: string, readonly status?: number) { super(message) }
  },
  streamIncidentEvents: mocks.stream,
}))

afterEach(() => { cleanup(); vi.restoreAllMocks(); mocks.incident.mockReset(); mocks.stream.mockReset() })

function StreamHarness() {
  useIncidentEventStream('incident-1')
  return null
}

describe('Incident SSE snapshot recovery', () => {
  it('applies a fresh Detail snapshot before every connection and uses its cursor, including zero', async () => {
    const order: string[] = []
    mocks.incident
      .mockImplementationOnce(async () => { order.push('detail:0'); return { eventCursor: 0 } })
      .mockImplementationOnce(async () => { order.push('detail:9'); return { eventCursor: 9 } })
    mocks.stream
      .mockImplementationOnce(async ({ lastEventId }: { lastEventId?: string }) => { order.push(`stream:${lastEventId}`) })
      .mockImplementationOnce(async ({ lastEventId }: { lastEventId?: string }) => {
        order.push(`stream:${lastEventId}`)
        return new Promise<void>(() => undefined)
      })
    const nativeSetTimeout = window.setTimeout.bind(window)
    vi.spyOn(window, 'setTimeout').mockImplementation((callback: TimerHandler, delay?: number, ...args: unknown[]) => {
      if ((delay ?? 0) > 1_000) return nativeSetTimeout(callback, delay, ...args)
      queueMicrotask(() => { if (typeof callback === 'function') callback(...args) })
      return 1
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    await act(async () => {
      render(<QueryClientProvider client={queryClient}><StreamHarness /></QueryClientProvider>)
    })

    await waitFor(() => expect(mocks.stream).toHaveBeenCalledTimes(2))
    expect(order).toEqual(['detail:0', 'stream:0', 'detail:9', 'stream:9'])
    expect(queryClient.getQueryData(['incidents', 'incident-1'])).toEqual({ eventCursor: 9 })
  })

  it('refreshes only the Timeline first page after a new deduplicated SSE event', async () => {
    mocks.incident.mockResolvedValue({ eventCursor: 4 })
    mocks.stream.mockImplementation(async ({ onEvent }: { onEvent: (frame: { id: string }, event: Record<string, unknown>) => void }) => {
      const event = { id: 'event-5', sequence: 5, type: 'step.updated', incidentId: 'incident-1', traceId: 'trace-1', version: 2, occurredAt: '2026-08-21T12:00:00Z', payload: {} }
      onEvent({ id: '5' }, event)
      onEvent({ id: '5' }, event)
      return new Promise<void>(() => undefined)
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    render(<QueryClientProvider client={queryClient}><StreamHarness /></QueryClientProvider>)

    await waitFor(() => expect(invalidate.mock.calls.filter(([filters]) => JSON.stringify(filters?.queryKey) === JSON.stringify(['incident-timeline', 'incident-1', { limit: 100, offset: 0 }]))).toHaveLength(1))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['incident-timeline', 'incident-1', { limit: 100, offset: 0 }], exact: true, refetchType: 'all' })
  })
})
