import { afterEach, describe, expect, it, vi } from 'vitest'
import { adminApi } from './adminApi'

afterEach(() => vi.unstubAllGlobals())

describe('Admin APIs', () => {
  it('paginates Principals and supports create/deactivate mutations', async () => {
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ url: String(url), method })
      if (method === 'GET') return new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '12', 'X-Limit': '100', 'X-Offset': '0' } })
      if (method === 'DELETE') return new Response(null, { status: 204 })
      return Response.json({ id: 'principal-2', accessToken: 'one-time', name: 'operator-2' }, { status: 201 })
    }))

    await expect(adminApi.principals({ limit: 100, offset: 0 })).resolves.toMatchObject({ items: [], totalCount: 12 })
    await adminApi.createPrincipal({ name: 'operator-2', kind: 'user', role: 'operator', unrestrictedEnvironments: false, environmentIds: [] })
    await adminApi.deactivatePrincipal('principal-2')
    expect(calls).toEqual([
      { url: expect.stringContaining('/principals?limit=100&offset=0'), method: 'GET' },
      { url: expect.stringMatching(/\/principals$/), method: 'POST' },
      { url: expect.stringContaining('/principals/principal-2'), method: 'DELETE' },
    ])
  })

  it('rotates Principal Token with the generated user path and CSRF Session credentials', async () => {
    document.cookie = 'opspilot_csrf=admin-csrf; path=/'
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toContain('/principals/principal-1/rotate-token')
      expect(init?.method).toBe('POST')
      expect(init?.credentials).toBe('include')
      expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('admin-csrf')
      return new Response(JSON.stringify({ principalId: 'principal-1', accessToken: 'one-time-token', tokenIssuedAt: '2026-08-12T00:00:00Z', tokenExpiresAt: '2026-09-11T00:00:00Z' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const result = await adminApi.rotatePrincipalToken('principal-1')
    expect(result.accessToken).toBe('one-time-token')
  })

  it('loads Outbox status and Dead Letters and replays by event ID', async () => {
    const paths: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request) => {
      paths.push(String(url))
      if (String(url).endsWith('/outbox/status')) return new Response(JSON.stringify({ pendingCount: 0, deadLetterCount: 0, oldestPendingAt: null, oldestPendingAgeSeconds: null }), { status: 200 })
      if (String(url).includes('/dead-letters/event-1/replay')) return new Response(JSON.stringify({ eventId: 'event-1', nextAttemptAt: '2026-08-12T00:00:00Z', status: 'queued' }), { status: 200 })
      return new Response('[]', { status: 200, headers: { 'X-Total-Count': '4', 'X-Limit': '100', 'X-Offset': '0' } })
    }))
    await adminApi.outboxStatus()
    await expect(adminApi.deadLetters({ limit: 100, offset: 0 })).resolves.toMatchObject({ totalCount: 4, items: [] })
    await adminApi.replayDeadLetter('event-1')
    expect(paths).toEqual(expect.arrayContaining([
      expect.stringContaining('/outbox/status'),
      expect.stringContaining('/outbox/dead-letters'),
      expect.stringContaining('/outbox/dead-letters/event-1/replay'),
    ]))
  })
})
