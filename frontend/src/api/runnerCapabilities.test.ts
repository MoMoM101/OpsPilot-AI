import { describe, expect, it } from 'vitest'
import type { Runner } from '../domain/types'
import { availableLogOperations, availableProbeOperations, availablePrometheusOperations, hostSnapshotAvailable } from './runnerCapabilities'

function runner(status: Runner['status'], observe: string[]): Runner {
  return {
    id: `${status}-runner`,
    name: `${status}-runner`,
    status,
    softwareVersion: '0.1.0',
    environmentId: null,
    capabilities: [{ connector: 'logs', contractVersion: '1.0', observe }],
    labels: {},
    lastSeenAt: '2026-08-09T01:00:00Z',
    leaseExpiresAt: '2026-08-09T01:01:00Z',
    version: 1,
    createdAt: '2026-08-09T01:00:00Z',
    updatedAt: '2026-08-09T01:00:00Z',
  }
}

describe('Runner log capabilities', () => {
  it('offers only operations declared by online Runners', () => {
    expect(availableLogOperations([
      runner('online', ['file.tail']),
      runner('offline', ['journal.query']),
    ])).toEqual(['file.tail'])
  })

  it('supports both bounded log operations', () => {
    expect(availableLogOperations([runner('online', ['journal.query', 'file.tail'])])).toEqual(['file.tail', 'journal.query'])
  })

  it('offers HTTP and TCP probes only when online Runners declare them', () => {
    expect(availableProbeOperations([
      runner('online', ['http.probe', 'tcp.probe']),
      runner('offline', ['file.tail']),
    ])).toEqual(['http.probe', 'tcp.probe'])
  })

  it('offers only declared Prometheus query modes', () => {
    expect(availablePrometheusOperations([
      runner('online', ['prometheus.query_range']),
      runner('offline', ['prometheus.query']),
    ])).toEqual(['prometheus.query_range'])
  })

  it('enables Host Snapshot only from an online Runner declaration', () => {
    expect(hostSnapshotAvailable([runner('online', ['host.snapshot'])])).toBe(true)
    expect(hostSnapshotAvailable([runner('offline', ['host.snapshot'])])).toBe(false)
  })
})
