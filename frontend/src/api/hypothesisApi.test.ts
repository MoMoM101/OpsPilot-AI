import { afterEach, describe, expect, it, vi } from 'vitest'
import { hypothesisApi } from './hypothesisApi'

afterEach(() => vi.unstubAllGlobals())

const response = {
  id: 'hypothesis-1', incidentId: 'incident-1', ordinal: 1, summary: 'Connection pool exhausted', confidence: 75,
  status: 'proposed', supportingEvidenceIds: [], contradictingEvidenceIds: [], version: 1,
  createdAt: '2026-08-10T01:00:00Z', updatedAt: '2026-08-10T01:00:00Z',
}

describe('Hypothesis API', () => {
  it('lists, creates and updates hypotheses using the Incident-scoped routes', async () => {
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      return new Response(JSON.stringify(method === 'GET' ? [response] : response), { status: method === 'POST' ? 201 : 200, headers: { 'Content-Type': 'application/json', ...(method === 'GET' ? { 'X-Total-Count': '21', 'X-Limit': '20', 'X-Offset': '20' } : {}) } })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(hypothesisApi.forIncident('incident-1', { limit: 20, offset: 20 })).resolves.toMatchObject({ totalCount: 21, limit: 20, offset: 20, items: [response] })
    await hypothesisApi.create('incident-1', { summary: response.summary, confidence: 75 })
    await hypothesisApi.update('incident-1', 'hypothesis-1', { expectedVersion: 1, status: 'supported' })

    expect(fetchMock.mock.calls.map(([url, init]) => [String(url), init?.method ?? 'GET'])).toEqual([
      [expect.stringContaining('/incidents/incident-1/hypotheses?limit=20&offset=20'), 'GET'],
      [expect.stringContaining('/incidents/incident-1/hypotheses'), 'POST'],
      [expect.stringContaining('/incidents/incident-1/hypotheses/hypothesis-1'), 'PATCH'],
    ])
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ expectedVersion: 1, status: 'supported' })
  })
})
