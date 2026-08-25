import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildCompensationPath, compensationApi } from './compensationApi'

afterEach(() => vi.unstubAllGlobals())

describe('Compensation API', () => {
  it('filters the list by Incident', () => {
    expect(buildCompensationPath({ incidentId: 'incident-1', limit: 20, offset: 5 })).toBe('/compensations?incidentId=incident-1&limit=20&offset=5')
  })

  it('reads the Incident-scoped total from pagination headers', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '8', 'X-Limit': '100', 'X-Offset': '0' } })))
    await expect(compensationApi.list({ incidentId: 'incident-1', limit: 100, offset: 0 })).resolves.toEqual({ items: [], totalCount: 8, limit: 100, offset: 0 })
  })

  it('creates a request with original parameters and a stable idempotency key', async () => {
    const body = { parameters: { replicas: 2 }, idempotencyKey: 'compensation-stable-1', expiresInSeconds: 3600 }
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toContain('/actions/action-1/compensation')
      expect(JSON.parse(String(init?.body))).toEqual(body)
      return new Response(JSON.stringify({ id: 'compensation-1' }), { status: 201, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await compensationApi.create('action-1', body)
  })

  it('uses expectedVersion for decision, dispatch and escalation, plus the frozen Resource Token for dispatch', async () => {
    const calls: Array<{ url: string; body?: unknown }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined })
      return new Response(JSON.stringify({ id: 'compensation-1' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    await compensationApi.decide('compensation-1', { decision: 'approve', expectedVersion: 1, comment: 'approved' })
    await compensationApi.dispatch('compensation-1', { expectedVersion: 2 })
    await compensationApi.execution('compensation-1')
    await compensationApi.escalate('compensation-1', { expectedVersion: 4, reason: 'manual takeover' })
    expect(calls).toEqual([
      { url: expect.stringContaining('/compensations/compensation-1/decision'), body: { decision: 'approve', expectedVersion: 1, comment: 'approved' } },
      { url: expect.stringContaining('/compensations/compensation-1/dispatch'), body: { expectedVersion: 2 } },
      { url: expect.stringContaining('/compensations/compensation-1/execution'), body: undefined },
      { url: expect.stringContaining('/compensations/compensation-1/escalate'), body: { expectedVersion: 4, reason: 'manual takeover' } },
    ])
  })
})
