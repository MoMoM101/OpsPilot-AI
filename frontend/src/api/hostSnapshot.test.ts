import { describe, expect, it } from 'vitest'
import type { Evidence } from '../domain/types'
import { formatBytes, formatDuration, parseHostSnapshot } from './hostSnapshot'

function evidence(content: string): Evidence {
  return { id: 'evidence-host', incidentId: 'incident-1', resourceId: 'resource-1', evidenceType: 'runner_observation', source: 'runner:runner-1:host', summary: 'Collected host snapshot', contentHash: 'hash', redacted: false, observedFrom: null, observedTo: null, collectedAt: '2026-08-09T01:00:00Z', collectionStatus: 'succeeded', timeConfidence: 'runner_reported', data: { operation: 'host.snapshot', content }, createdAt: '2026-08-09T01:00:00Z', updatedAt: '2026-08-09T01:00:00Z' }
}

describe('Host Snapshot parser', () => {
  it('accepts a cross-platform snapshot without Linux-only fields', () => {
    const snapshot = parseHostSnapshot(evidence('{"schemaVersion":"1.0","platform":{"system":"Windows","hostname":"win-runner"},"cpu":{"logicalCount":8},"disk":{"totalBytes":1000,"freeBytes":400}}'))
    expect(snapshot?.platform?.system).toBe('Windows')
    expect(snapshot?.memory).toBeUndefined()
    expect(snapshot?.network).toBeUndefined()
    expect(snapshot?.uptimeSeconds).toBeUndefined()
    expect(snapshot?.processCount).toBeUndefined()
  })

  it('formats missing optional values as 未提供', () => {
    expect(formatBytes(undefined)).toBe('未提供')
    expect(formatDuration(undefined)).toBe('未提供')
  })
})
