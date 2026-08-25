import { afterEach, describe, expect, it, vi } from 'vitest'
import { planApi } from './planApi'

afterEach(() => vi.unstubAllGlobals())

describe('Plan API', () => {
  it('loads the current plan and preserves running PlanStep IDs', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      id: 'plan-1', incidentId: 'incident-1', version: 2, objective: 'Diagnose latency', status: 'active', maxToolCalls: 10, maxDurationSeconds: 600, replanCount: 0,
      steps: [{ id: 'step-1', ordinal: 1, title: 'Query metrics', objective: 'Collect metrics', kind: 'observe', status: 'running', risk: 'read_only', attempts: 1, evidenceIds: [], resultSummary: null, version: 2, createdAt: '2026-08-10T01:00:00Z', updatedAt: '2026-08-10T01:01:00Z' }],
      createdAt: '2026-08-10T01:00:00Z', updatedAt: '2026-08-10T01:01:00Z',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const plan = await planApi.current('incident-1')
    expect(plan).toMatchObject({ status: 'active', steps: [{ id: 'step-1', status: 'running' }] })
  })

  it('returns null when the Incident has no plan', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'PLAN_NOT_FOUND', message: 'Incident has no plan' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })))
    await expect(planApi.current('incident-1')).resolves.toBeNull()
  })
})
