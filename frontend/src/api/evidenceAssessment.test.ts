import { describe, expect, it } from 'vitest'
import type { Evidence } from '../domain/types'
import { assessEvidence, evidenceCropFlags, evidenceIsTruncated, evidenceResultIsCropped } from './evidenceAssessment'

function evidence(data: Record<string, unknown>): Evidence {
  return { id: 'evidence-1', incidentId: 'incident-1', resourceId: 'resource-1', evidenceType: 'runner_observation', source: 'runner:runner-1:http', summary: 'HTTP probe status=503 healthy=false', contentHash: 'hash', redacted: false, observedFrom: null, observedTo: '2026-08-09T01:00:00Z', collectedAt: '2026-08-09T01:00:00Z', collectionStatus: 'succeeded', timeConfidence: 'runner_reported', data, createdAt: '2026-08-09T01:00:00Z', updatedAt: '2026-08-09T01:00:00Z' }
}

describe('Evidence assessment', () => {
  it('marks an executed HTTP probe unhealthy from Evidence content', () => {
    expect(assessEvidence(evidence({ operation: 'http.probe', content: '{"reachable":true,"statusCode":503,"healthy":false,"latencyMs":18.4}' }))).toMatchObject({ state: 'unhealthy', label: '目标不健康' })
  })

  it('reads TCP reachability from Evidence rather than task status', () => {
    expect(assessEvidence(evidence({ operation: 'tcp.probe', content: '{"reachable":true,"latencyMs":3.2}' }))).toMatchObject({ state: 'healthy', label: '目标可达' })
  })

  it('recognizes the normalized truncation marker', () => {
    expect(evidenceIsTruncated(evidence({ outputTruncated: true }))).toBe(true)
  })

  it('recognizes Prometheus series and sample cropping inside bounded content', () => {
    const item = evidence({
      operation: 'prometheus.query_range',
      content: '{"seriesTruncated":true,"data":{"result":[{"samplesTruncated":true}]}}',
    })
    expect(evidenceCropFlags(item)).toEqual({ outputTruncated: false, seriesTruncated: true, samplesTruncated: true })
    expect(evidenceResultIsCropped(item)).toBe(true)
  })
})
