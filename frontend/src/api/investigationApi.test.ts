import { afterEach, describe, expect, it, vi } from 'vitest'
import { investigationApi } from './investigationApi'

afterEach(() => vi.unstubAllGlobals())

describe('Investigation API', () => {
  it('creates a run without graphVersion so the backend selects graph-v1', async () => {
    const body = { idempotencyKey: 'investigation-run-001', maxIterations: 20 }
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(init?.method).toBe('POST')
      expect(JSON.parse(String(init?.body))).toEqual(body)
      return new Response(JSON.stringify({ id: 'run-1', graphVersion: 'graph-v1', status: 'queued', runtimeAttempt: 0 }), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    const run = await investigationApi.create('incident-1', body)
    expect(run.graphVersion).toBe('graph-v1')
  })

  it('allows graph-v1 and maxModelRequests to be sent explicitly', async () => {
    const body = { idempotencyKey: 'investigation-run-002', graphVersion: 'graph-v1' as const, maxModelRequests: 20 }
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual(body)
      return new Response(JSON.stringify({ id: 'run-2', graphVersion: 'graph-v1', status: 'queued', runtimeAttempt: 0 }), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await investigationApi.create('incident-1', body)
  })

  it('uses read-only run and Checkpoint endpoints', async () => {
    const fetchMock = vi.fn(async (url: string | URL | Request, _init?: RequestInit) => {
      const value = String(url)
      if (value.includes('/checkpoints')) return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (value.includes('/investigation-runs/run-1')) return new Response(JSON.stringify({ id: 'run-1', status: 'running' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '7', 'X-Limit': '20', 'X-Offset': '0' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(investigationApi.forIncident('incident-1', { limit: 20, offset: 0 })).resolves.toMatchObject({ totalCount: 7, limit: 20, offset: 0 })
    await investigationApi.detail('run-1')
    await investigationApi.checkpoints('run-1', { afterSequence: 3, limit: 100 })

    const urls = fetchMock.mock.calls.map(([url]) => String(url))
    expect(urls[0]).toContain('/incidents/incident-1/investigation-runs?limit=20&offset=0')
    expect(urls[1]).toContain('/investigation-runs/run-1')
    expect(urls[2]).toContain('/investigation-runs/run-1/checkpoints?after_sequence=3&limit=100')
    expect(fetchMock.mock.calls.every(([, init]) => !init || init.method === undefined || init.method === 'GET')).toBe(true)
  })

  it('paginates HITL Waits while keeping Checkpoints on after_sequence', async () => {
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      const value = String(url)
      if (value.includes('/hitl-waits')) return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '12', 'X-Limit': '10', 'X-Offset': '10' } })
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(investigationApi.hitlWaits('run-1', { limit: 10, offset: 10 })).resolves.toEqual({ items: [], totalCount: 12, limit: 10, offset: 10 })
    await investigationApi.checkpoints('run-1', { afterSequence: 12, limit: 50 })

    const urls = fetchMock.mock.calls.map(([url]) => String(url))
    expect(urls[0]).toContain('/investigation-runs/run-1/hitl-waits?limit=10&offset=10')
    expect(urls[1]).toContain('/investigation-runs/run-1/checkpoints?after_sequence=12&limit=50')
    expect(urls[1]).not.toContain('offset')
  })
})
