import { afterEach, describe, expect, it, vi } from 'vitest'
import { policyApi } from './policyApi'

afterEach(() => vi.unstubAllGlobals())

describe('Policy API', () => {
  it('loads rules with the backend Environment filter', async () => {
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      expect(String(url)).toContain('/policies?environmentId=environment-1&limit=100&offset=0')
      return new Response('[]', { status: 200, headers: { 'X-Total-Count': '3', 'X-Limit': '100', 'X-Offset': '0' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(policyApi.rules({ environmentId: 'environment-1', limit: 100, offset: 0 })).resolves.toMatchObject({ totalCount: 3, limit: 100, offset: 0 })
  })

  it('returns the backend Dry Run decision without evaluating it in the frontend', async () => {
    const backendDecision = { allowed: false, approvalRequired: true, matchedRuleId: 'rule-1', matchedRuleName: 'deny-high-risk', matchedRuleVersion: 4, remainingExecutions: 2, effect: 'deny', reason: 'Matched deny rule' }
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toContain('/policies/dry-run')
      expect(init?.method).toBe('POST')
      return new Response(JSON.stringify(backendDecision), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const decision = await policyApi.dryRun({ environmentId: 'env-1', resourceId: 'resource-1', capability: 'action.execute', autonomyLevel: 'L2', risk: 'high' })
    expect(decision).toEqual(backendDecision)
  })

  it('updates a rule with PUT and expectedVersion', async () => {
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toContain('/policies/rule-1')
      expect(init?.method).toBe('PUT')
      expect(JSON.parse(String(init?.body))).toMatchObject({ expectedVersion: 3, maintenanceDays: [0, 4], maintenanceStartMinute: 60, maintenanceEndMinute: 120, maxExecutionsPerIncident: 2 })
      return new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await policyApi.update('rule-1', {
      environmentId: 'env-1',
      name: 'maintenance-rule',
      effect: 'allow',
      approvalRequired: false,
      enabled: true,
      priority: 100,
      expectedVersion: 3,
      maintenanceDays: [0, 4],
      maintenanceStartMinute: 60,
      maintenanceEndMinute: 120,
      maxExecutionsPerIncident: 2,
    })
  })

  it('does not expose the quota-consuming evaluate operation in the page API client', () => {
    expect(policyApi).not.toHaveProperty('evaluate')
  })
})
