import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IncidentTimelinePanel } from './IncidentDetailPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function event(id: string, summary: string) {
  return { id, type: 'step.updated', occurredAt: '2026-08-21T12:00:00Z', actorType: 'agent', actorId: null, payload: { summary } }
}

describe('Incident Timeline pagination', () => {
  it('offers older pages for a truncated snapshot and uses header totals', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), 'http://localhost')
      const offset = Number(url.searchParams.get('offset'))
      expect(url.pathname).toBe('/api/v1/incidents/incident-1/timeline')
      expect(url.searchParams.get('limit')).toBe('100')
      expect(url.searchParams.has('eventCursor')).toBe(false)
      return new Response(JSON.stringify([offset === 0 ? event('new', '最新事件') : event('old', '更早事件')]), { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '106', 'X-Limit': '100', 'X-Offset': String(offset) } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><IncidentTimelinePanel incident={{ id: 'incident-1', timeline: [], timelineTotal: 106, timelineTruncated: true }} /></QueryClientProvider>)

    expect(await screen.findByText('最新事件')).toBeInTheDocument()
    expect(screen.getByText('106 EVENTS')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))

    expect(await screen.findByText('更早事件')).toBeInTheDocument()
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => new URL(String(input), 'http://localhost').searchParams.get('offset') === '100')).toBe(true))
  })

  it('uses the complete Detail Timeline directly when it is not truncated', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><IncidentTimelinePanel incident={{ id: 'incident-1', timeline: [{ id: 'snapshot', type: 'event', occurredAt: '12:00:00', title: '完整快照事件', detail: 'detail' }], timelineTotal: 1, timelineTruncated: false }} /></QueryClientProvider>)

    expect(screen.getByText('完整快照事件')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '列表分页' })).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
