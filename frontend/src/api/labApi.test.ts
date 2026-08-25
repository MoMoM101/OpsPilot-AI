import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildLabMutationPath, labApi } from './labApi'

afterEach(() => vi.unstubAllGlobals())

describe('Fault Lab API', () => {
  it('encodes scenario identifiers in mutation paths', () => {
    expect(buildLabMutationPath('qdrant/down', 'inject'))
      .toBe('/lab/scenarios/qdrant%2Fdown/inject')
  })

  it('lists scenarios and sends a stable idempotency key for injection', async () => {
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      const payload = init?.method === 'POST'
        ? { scenario: { id: 'qdrant_down', active: true }, replayed: false }
        : []
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }))

    await labApi.list()
    await labApi.mutate('qdrant_down', 'inject', { idempotencyKey: 'stable-inject-key' })

    expect(calls).toEqual([
      { url: expect.stringContaining('/lab/scenarios'), method: 'GET', body: undefined },
      {
        url: expect.stringContaining('/lab/scenarios/qdrant_down/inject'),
        method: 'POST',
        body: { idempotencyKey: 'stable-inject-key' },
      },
    ])
  })
})
