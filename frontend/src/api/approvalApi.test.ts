import { afterEach, describe, expect, it, vi } from 'vitest'
import { approvalApi, buildApprovalPath } from './approvalApi'

afterEach(() => vi.unstubAllGlobals())

describe('Approval API', () => {
  it('builds Incident and status filters using the OpenAPI query names', () => {
    expect(buildApprovalPath({ incidentId: 'incident-1', status: 'pending', limit: 25, offset: 5 }))
      .toBe('/approvals?incidentId=incident-1&status=pending&limit=25&offset=5')
  })

  it('submits decisions with expectedVersion and bounded parameter edits', async () => {
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toContain('/approvals/approval-1/decision')
      expect(init?.method).toBe('POST')
      expect(JSON.parse(String(init?.body))).toEqual({
        decision: 'approve',
        comment: 'reviewed',
        expectedVersion: 4,
        parameterEdits: { replicas: 2 },
      })
      return new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await approvalApi.decide('approval-1', { decision: 'approve', comment: 'reviewed', expectedVersion: 4, parameterEdits: { replicas: 2 } })
  })
})
