import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSseParser, streamIncidentEvents } from './sseClient'
import { clearClientCredentials, setAlphaBearerToken } from '../auth/authSession'

afterEach(() => { vi.unstubAllGlobals(); clearClientCredentials() })

describe('SSE client', () => {
  it('parses chunked frames and ignores heartbeat comments', () => {
    const frames: Array<{ id: string; type: string; data: string }> = []
    const parser = createSseParser((event) => frames.push(event))
    parser.push(': heart')
    parser.push('beat\r\n\r\nid: 17\r\nevent: step.updated\r\ndata: {"sequence":17,')
    parser.push('"type":"step.updated"}\r\n\r\n')

    expect(frames).toEqual([{ id: '17', type: 'step.updated', data: '{"sequence":17,"type":"step.updated"}' }])
  })

  it('sends Last-Event-ID when resuming a stream', async () => {
    setAlphaBearerToken('sse-user-token-1234567890')
    const body = 'id: 18\nevent: incident.updated\ndata: {"id":"event-18","sequence":18,"type":"incident.updated","incidentId":"incident-1","traceId":"trace-1","version":2,"occurredAt":"2026-08-08T01:00:00Z","payload":{}}\n\n'
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('Last-Event-ID')).toBe('17')
      expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer sse-user-token-1234567890')
      return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const received: string[] = []

    await streamIncidentEvents({
      incidentId: 'incident-1',
      lastEventId: '17',
      signal: new AbortController().signal,
      onOpen: () => undefined,
      onEvent: (frame) => received.push(frame.id),
    })

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(received).toEqual(['18'])
  })

  it('sends zero as a valid Last-Event-ID', async () => {
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('Last-Event-ID')).toBe('0')
      return new Response('', { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await streamIncidentEvents({ incidentId: 'incident-1', lastEventId: '0', signal: new AbortController().signal, onOpen: vi.fn(), onEvent: vi.fn() })
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it.each([[401, 'authentication'], [403, 'permission']] as const)('classifies HTTP %s without treating it as a network retry', async (status, kind) => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status })))
    await expect(streamIncidentEvents({ incidentId: 'incident-1', signal: new AbortController().signal, onOpen: vi.fn(), onEvent: vi.fn() })).rejects.toMatchObject({ kind, status })
  })
})
