import { afterEach, describe, expect, it, vi } from 'vitest'
import { actionProposalApi, buildActionProposalPath } from './actionProposalApi'

afterEach(() => vi.unstubAllGlobals())

describe('Action Proposal API', () => {
  it('uses the contract query names for Incident and status filters', () => {
    expect(buildActionProposalPath({ incidentId: 'incident-1', status: 'awaiting_approval', limit: 20, offset: 5 }))
      .toBe('/action-proposals?incident_id=incident-1&status=awaiting_approval&limit=20&offset=5')
  })

  it('loads the read-only proposal list', async () => {
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toContain('/action-proposals?incident_id=incident-1')
      expect(init?.method ?? 'GET').toBe('GET')
      return new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '5', 'X-Limit': '50', 'X-Offset': '0' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(actionProposalApi.list({ incidentId: 'incident-1' })).resolves.toMatchObject({ items: [], totalCount: 5 })
  })
})
