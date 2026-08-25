import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildIncidentEvidencePath, evidenceApi } from './evidenceApi'

afterEach(() => vi.unstubAllGlobals())

describe('Evidence API', () => {
  it('builds the Incident-scoped list endpoint and filters', () => {
    const url = new URL(buildIncidentEvidencePath('incident-1', {
      evidenceType: 'runner_observation',
      resourceId: 'resource-1',
      limit: 25,
      offset: 50,
    }), 'http://localhost')
    expect(url.pathname).toBe('/incidents/incident-1/evidence')
    expect(Object.fromEntries(url.searchParams)).toEqual({ evidence_type: 'runner_observation', resource_id: 'resource-1', limit: '25', offset: '50' })
  })

  it('uses pagination headers as the filtered Evidence total', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '31', 'X-Limit': '25', 'X-Offset': '25' } })))
    await expect(evidenceApi.forIncident('incident-1', { evidenceType: 'log', limit: 25, offset: 25 })).resolves.toEqual({ items: [], totalCount: 31, limit: 25, offset: 25 })
  })
})
