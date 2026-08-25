import { afterEach, describe, expect, it, vi } from 'vitest'
import { demoApi } from './demoApi'

afterEach(() => vi.unstubAllGlobals())

describe('Demo API', () => {
  it('uses the three generated-contract endpoints and only sends generation for cleanup', async () => {
    const fetchMock = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => new Response(JSON.stringify(
      init?.method === 'POST' ? { status: 'inactive', replayed: false, deletedIncidentCount: 0 } : { status: 'inactive' },
    ), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await demoApi.status()
    await demoApi.initialize()
    await demoApi.cleanup(7)

    expect(fetchMock.mock.calls[0][0]).toContain('/demo/status')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('GET')
    expect(fetchMock.mock.calls[1][0]).toContain('/demo/initialize')
    expect(fetchMock.mock.calls[1][1]?.method).toBe('POST')
    expect(fetchMock.mock.calls[1][1]?.body).toBeUndefined()
    expect(fetchMock.mock.calls[2][0]).toContain('/demo/cleanup')
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ expectedGeneration: 7 })
  })
})
