import { describe, expect, it } from 'vitest'
import { buildAuditPath } from './auditApi'

describe('Audit API filters', () => {
  it('serializes all five server filters with pagination', () => {
    const path = buildAuditPath({ actorId: 'admin-1', action: 'auth.session.create', outcome: 'failure', from: '2026-08-20T00:00:00.000Z', to: '2026-08-21T00:00:00.000Z', limit: 50, offset: 100 })
    const url = new URL(path, 'http://local')
    expect(Object.fromEntries(url.searchParams)).toEqual({ actorId: 'admin-1', action: 'auth.session.create', outcome: 'failure', from: '2026-08-20T00:00:00.000Z', to: '2026-08-21T00:00:00.000Z', limit: '50', offset: '100' })
  })
})
