import { beforeEach, describe, expect, it } from 'vitest'
import type { AgentEventDto } from './contracts'
import { createEventIdDeduplicator, evidenceIdForAgentEvent, queryKeysForAgentEvent, readLastEventId, saveLastEventId } from './incidentStream'

const event = (type: string): AgentEventDto => ({
  id: 'event-1',
  sequence: 7,
  type,
  incidentId: 'incident-1',
  traceId: 'trace-1',
  version: 2,
  occurredAt: '2026-08-08T01:00:00Z',
  payload: {},
})

describe('Incident stream state', () => {
  beforeEach(() => window.localStorage.clear())

  it('persists the cursor separately for each Incident', () => {
    saveLastEventId('incident-1', '7')
    saveLastEventId('incident-2', '3')
    expect(readLastEventId('incident-1')).toBe('7')
    expect(readLastEventId('incident-2')).toBe('3')
  })

  it('keeps zero as a valid persisted snapshot cursor', () => {
    saveLastEventId('incident-1', '0')
    expect(readLastEventId('incident-1')).toBe('0')
  })

  it('deduplicates repeated increments by the SSE id', () => {
    const eventIds = createEventIdDeduplicator()
    expect(eventIds.accept('17')).toBe(true)
    expect(eventIds.accept('17')).toBe(false)
    expect(eventIds.accept('18')).toBe(true)
  })

  it('invalidates Incident list, detail and Dashboard for Incident events', () => {
    expect(queryKeysForAgentEvent(event('incident.status_changed'))).toEqual([
      ['incidents', 'incident-1'],
      ['incidents'],
      ['dashboard'],
    ])
  })

  it.each(['incident.observability_lost', 'incident.observability_restored'])('refreshes observation-plane snapshots for %s', (type) => {
    expect(queryKeysForAgentEvent(event(type))).toEqual([
      ['incidents', 'incident-1'],
      ['incidents'],
      ['dashboard'],
      ['runners'],
      ['runner-tasks', { incidentId: 'incident-1' }],
    ])
  })

  it('invalidates Incident detail, Plan and Dashboard for plan events', () => {
    expect(queryKeysForAgentEvent(event('step.updated'))).toEqual([
      ['incidents', 'incident-1'],
      ['plans', 'incident-1'],
      ['dashboard'],
    ])
  })

  it.each(['hypothesis.created', 'hypothesis.updated'])('refreshes the hypothesis list and primary Incident hypothesis for %s', (type) => {
    expect(queryKeysForAgentEvent(event(type))).toEqual([
      ['incidents', 'incident-1'],
      ['hypotheses', 'incident-1'],
      ['incidents'],
      ['dashboard'],
    ])
  })

  it.each(['investigation.run_created', 'investigation.status_changed'])('refreshes the InvestigationRun snapshot for %s', (type) => {
    const investigationEvent = { ...event(type), payload: { runId: 'run-1' } }
    expect(queryKeysForAgentEvent(investigationEvent)).toEqual([
      ['incidents', 'incident-1'],
      ['investigation-runs', 'incident-1'],
      ['dashboard'],
      ['investigation-run', 'run-1'],
    ])
  })

  it('refreshes both the run and Checkpoint timeline after investigation.checkpointed', () => {
    const checkpointed = { ...event('investigation.checkpointed'), payload: { runId: 'run-1', checkpointId: 'checkpoint-1' } }
    expect(queryKeysForAgentEvent(checkpointed)).toEqual([
      ['incidents', 'incident-1'],
      ['investigation-runs', 'incident-1'],
      ['dashboard'],
      ['investigation-run', 'run-1'],
      ['investigation-checkpoints', 'run-1'],
    ])
  })

  it('refreshes the recovered Run and its latest Checkpoint state', () => {
    const recovered = { ...event('investigation.runtime_recovered'), payload: { runId: 'run-1', runtimeAttempt: 2 } }
    expect(queryKeysForAgentEvent(recovered)).toEqual([
      ['incidents', 'incident-1'],
      ['investigation-runs', 'incident-1'],
      ['dashboard'],
      ['investigation-run', 'run-1'],
      ['investigation-checkpoints', 'run-1'],
    ])
  })

  it('invalidates filtered Alert queries for alert events', () => {
    expect(queryKeysForAgentEvent(event('alert.resolved'))).toEqual([
      ['incidents', 'incident-1'],
      ['alerts'],
    ])
  })

  it.each(['approval.requested', 'approval.resolved'])('invalidates Approval snapshots for %s', (type) => {
    expect(queryKeysForAgentEvent(event(type))).toEqual([
      ['incidents', 'incident-1'],
      ['approvals'],
    ])
  })

  it.each(['action.requested', 'action.cancelled'])('invalidates Action snapshots for %s', (type) => {
    expect(queryKeysForAgentEvent(event(type))).toEqual([
      ['incidents', 'incident-1'],
      ['actions'],
    ])
  })

  it.each(['action.proposal_created', 'action.proposal_resolved'])('invalidates Action Proposal snapshots for %s', (type) => {
    expect(queryKeysForAgentEvent(event(type))).toEqual([
      ['incidents', 'incident-1'],
      ['action-proposals'],
    ])
  })

  it.each(['resource_lock.acquired', 'resource_lock.released'])('invalidates active Resource Lock snapshots for %s', (type) => {
    expect(queryKeysForAgentEvent(event(type))).toEqual([
      ['incidents', 'incident-1'],
      ['resource-locks'],
    ])
  })

  it.each(['action.dispatched', 'action.started', 'action.succeeded', 'action.failed', 'action.unknown'])('refreshes Action and Execution for %s', (type) => {
    const executionEvent = { ...event(type), payload: { actionId: 'action-1', executionId: 'execution-1' } }
    expect(queryKeysForAgentEvent(executionEvent)).toEqual([
      ['incidents', 'incident-1'],
      ['actions'],
      ['action-execution', 'action-1'],
    ])
  })

  it('refreshes Action, Execution and the released Resource Lock after reconciliation', () => {
    const reconciled = { ...event('action.reconciled'), payload: { actionId: 'action-1', executionId: 'execution-1' } }
    expect(queryKeysForAgentEvent(reconciled)).toEqual([
      ['incidents', 'incident-1'],
      ['actions'],
      ['action-execution', 'action-1'],
      ['resource-locks'],
    ])
  })

  it.each(['action.verification_queued', 'action.verification_passed', 'action.verification_failed'])('refreshes verification dependencies for %s', (type) => {
    const verificationEvent = { ...event(type), payload: { actionId: 'action-1', verificationId: 'verification-1' } }
    expect(queryKeysForAgentEvent(verificationEvent)).toEqual([
      ['incidents', 'incident-1'],
      ['actions'],
      ['action-verification', 'action-1'],
      ['runner-tasks', { incidentId: 'incident-1' }],
      ['incident-evidence', 'incident-1'],
      ['resource-locks'],
    ])
  })

  it.each(['compensation.requested', 'compensation.resolved', 'compensation.dispatched', 'compensation.started'])('refreshes Compensation state for %s', (type) => {
    const compensationEvent = { ...event(type), payload: { actionId: 'action-1', compensationId: 'compensation-1' } }
    expect(queryKeysForAgentEvent(compensationEvent)).toEqual([
      ['incidents', 'incident-1'],
      ['actions'],
      ['compensations'],
      ['compensation-execution', 'compensation-1'],
    ])
  })

  it.each(['compensation.succeeded', 'compensation.escalated', 'compensation.unknown'])('also refreshes frozen Resource Locks for %s', (type) => {
    const compensationEvent = { ...event(type), payload: { actionId: 'action-1', compensationId: 'compensation-1' } }
    expect(queryKeysForAgentEvent(compensationEvent)).toEqual([
      ['incidents', 'incident-1'],
      ['actions'],
      ['compensations'],
      ['compensation-execution', 'compensation-1'],
      ['resource-locks'],
    ])
  })

  it('invalidates the corresponding RunnerTask snapshots', () => {
    const succeeded = { ...event('runner_task.succeeded'), payload: { evidenceId: 'evidence-1' } }
    expect(queryKeysForAgentEvent(succeeded)).toEqual([
      ['incidents', 'incident-1'],
      ['runner-tasks', { incidentId: 'incident-1' }],
      ['incident-evidence', 'incident-1'],
    ])
    expect(evidenceIdForAgentEvent(succeeded)).toBe('evidence-1')
    expect(evidenceIdForAgentEvent(event('runner_task.failed'))).toBeUndefined()
  })

  it('refreshes RunnerTask, current Plan and Dashboard when a task is cancelled', () => {
    const cancelled = { ...event('runner_task.cancelled'), payload: { taskId: 'task-1', planStepId: 'step-1', reason: 'PLAN_SUPERSEDED' } }
    expect(queryKeysForAgentEvent(cancelled)).toEqual([
      ['incidents', 'incident-1'],
      ['runner-tasks', { incidentId: 'incident-1' }],
      ['plans', 'incident-1'],
      ['dashboard'],
    ])
    expect(evidenceIdForAgentEvent(cancelled)).toBeUndefined()
  })
})
