import { describe, expect, it } from 'vitest'
import { buildAlertPath } from './alertApi'

describe('Alert API', () => {
  it('uses the backend snake_case filter parameters', () => {
    const path = buildAlertPath({
      status: 'firing',
      resourceId: '019fdb57-c58c-7200-bae7-6dbb07bb34ad',
      incidentId: '019fdb57-c58c-7200-bae7-6dbb07bb34ae',
      limit: 25,
      offset: 50,
    })

    const url = new URL(path, 'http://localhost')
    expect(url.pathname).toBe('/alerts')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      status: 'firing',
      resource_id: '019fdb57-c58c-7200-bae7-6dbb07bb34ad',
      incident_id: '019fdb57-c58c-7200-bae7-6dbb07bb34ae',
      limit: '25',
      offset: '50',
    })
  })

  it('omits empty filters', () => {
    expect(buildAlertPath()).toBe('/alerts')
  })
})
