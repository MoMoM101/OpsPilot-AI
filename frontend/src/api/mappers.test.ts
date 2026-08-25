import { describe, expect, it } from 'vitest'
import type { DashboardDto, IncidentDetailDto } from './contracts'
import { mapDashboard, mapIncidentDetail } from './mappers'

const incident = {
  id: '018fdb57-c58c-7200-bae7-6dbb07bb34ad',
  title: 'API latency increased',
  status: 'INVESTIGATING',
  severity: 'high',
  resource: 'payments-api',
  environment: 'prod',
  resourceId: 'service/payments-api',
  owner: null,
  observabilityStatus: 'lost',
  observabilityRunnerId: 'runner-1',
  observabilityLostAt: '2026-08-07T02:04:00Z',
  hypothesis: { id: 'hypothesis-1', ordinal: 1, summary: 'Connection pool exhausted', confidence: 82, status: 'supported' },
  version: 4,
  createdAt: '2026-08-07T02:00:00Z',
  updatedAt: '2026-08-07T02:05:00Z',
} satisfies DashboardDto['incidents'][number]

describe('API DTO mappers', () => {
  it('maps the dashboard response without leaking transport DTOs into pages', () => {
    const dto: DashboardDto = {
      activeTasks: 3,
      waitingHuman: 1,
      rootCauseRate: 0.82,
      meanInvestigationSeconds: 95,
      runnerOnline: 4,
      runnerTotal: 5,
      safety: { pendingApprovals: 2, activeResourceLocks: 3, unknownActions: 4, actionsRequiringAttention: 7, observabilityLostIncidents: 5 },
      incidents: [incident],
    }

    const result = mapDashboard(dto)
    expect(result.incidents[0]).toMatchObject({
      resourceId: 'service/payments-api',
      environment: 'prod',
      observabilityStatus: 'lost',
      observabilityRunnerId: 'runner-1',
      observabilityLostAt: '2026-08-07T02:04:00Z',
      hypothesis: { id: 'hypothesis-1', ordinal: 1, confidence: 82, status: 'supported' },
      version: 4,
    })
    expect(result.waitingHuman).toBe(1)
    expect(result.safety).toEqual({ pendingApprovals: 2, activeResourceLocks: 3, unknownActions: 4, actionsRequiringAttention: 7, observabilityLostIncidents: 5 })
  })

  it.each(['failed', 'skipped'] as const)('preserves the %s plan-step status', (status) => {
    const dto: IncidentDetailDto = {
      ...incident,
      traceId: 'trace-123',
      eventCursor: 0,
      timelineTotal: 1,
      timelineTruncated: false,
      autonomyLevel: 'L2',
      planVersion: 2,
      replanCount: 1,
      toolBudget: { used: 2, limit: 8 },
      steps: [{
        id: `step-${status}`,
        ordinal: 1,
        title: 'Inspect recent deployment',
        objective: 'Find a causal change',
        kind: 'analyze',
        status,
        risk: 'read_only',
        attempts: 1,
        evidenceIds: ['evidence-1'],
        resultSummary: status === 'failed' ? 'Connector timed out' : null,
        version: 2,
        createdAt: '2026-08-07T02:01:00Z',
        updatedAt: '2026-08-07T02:02:00Z',
      }],
      timeline: [{
        id: 'event-1',
        type: 'tool.completed',
        occurredAt: '2026-08-07T02:02:00Z',
        actorType: 'agent',
        actorId: 'investigator',
        payload: { summary: 'Log query completed' },
      }],
    }

    const result = mapIncidentDetail(dto)
    expect(result.steps[0].status).toBe(status)
    expect(result.timeline[0]).toMatchObject({ type: 'tool', detail: 'Log query completed' })
    expect(result.traceId).toBe('trace-123')
    expect(result.eventCursor).toBe(0)
    expect(result.timelineTotal).toBe(1)
    expect(result.timelineTruncated).toBe(false)
  })
})
