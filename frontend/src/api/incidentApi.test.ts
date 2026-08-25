import { describe, expect, it } from 'vitest'
import { buildIncidentListPath, buildIncidentTimelinePath, incidentApi } from './incidentApi'
import { afterEach, vi } from 'vitest'

afterEach(() => vi.unstubAllGlobals())

describe('Incident API', () => {
  it('passes supported filters to the backend', () => {
    const path = buildIncidentListPath({ status: 'INVESTIGATING', severity: 'high', environmentId: 'env-1', q: 'database timeout', limit: 25, offset: 50 })
    const url = new URL(path, 'http://localhost')

    expect(url.pathname).toBe('/incidents')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      status: 'INVESTIGATING',
      severity: 'high',
      environmentId: 'env-1',
      q: 'database timeout',
      limit: '25',
      offset: '50',
    })
  })

  it('omits empty filters', () => {
    expect(buildIncidentListPath()).toBe('/incidents')
  })

  it('uses limit and offset for Timeline without treating an event cursor as an offset', () => {
    const path = buildIncidentTimelinePath('incident/id', { limit: 100, offset: 200 })
    const url = new URL(path, 'http://localhost')
    expect(url.pathname).toBe('/incidents/incident%2Fid/timeline')
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: '100', offset: '200' })
    expect(path).not.toContain('eventCursor')
  })

  it('reads Timeline totals and page coordinates from response headers', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '106', 'X-Limit': '100', 'X-Offset': '0' } })))
    await expect(incidentApi.timeline('incident-1', { limit: 100, offset: 0 })).resolves.toEqual({ items: [], totalCount: 106, limit: 100, offset: 0 })
  })
})
