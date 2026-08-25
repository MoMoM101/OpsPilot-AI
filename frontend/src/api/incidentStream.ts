import type { QueryKey } from '@tanstack/react-query'
import type { AgentEventDto } from './contracts'

const cursorPrefix = 'opspilot:sse:last-event-id:'

export function createEventIdDeduplicator() {
  const processed = new Set<string>()
  return {
    accept(eventId: string): boolean {
      if (processed.has(eventId)) return false
      processed.add(eventId)
      return true
    },
  }
}

export function readLastEventId(incidentId: string): string | undefined {
  try {
    return window.localStorage.getItem(`${cursorPrefix}${incidentId}`) ?? undefined
  } catch {
    return undefined
  }
}

export function saveLastEventId(incidentId: string, eventId: string): void {
  if (!eventId) return
  try {
    window.localStorage.setItem(`${cursorPrefix}${incidentId}`, eventId)
  } catch {
    // The stream remains usable when storage is unavailable.
  }
}

export function queryKeysForAgentEvent(event: AgentEventDto): QueryKey[] {
  const keys: QueryKey[] = [['incidents', event.incidentId]]
  if (event.type.startsWith('incident.')) {
    keys.push(['incidents'], ['dashboard'])
  }
  if (event.type === 'incident.observability_lost' || event.type === 'incident.observability_restored') {
    keys.push(['runners'], ['runner-tasks', { incidentId: event.incidentId }])
  }
  if (event.type === 'hypothesis.created' || event.type === 'hypothesis.updated') {
    keys.push(['hypotheses', event.incidentId], ['incidents'], ['dashboard'])
  }
  if (event.type === 'investigation.run_created' || event.type === 'investigation.status_changed' || event.type === 'investigation.checkpointed' || event.type === 'investigation.runtime_recovered') {
    keys.push(['investigation-runs', event.incidentId], ['dashboard'])
    const runId = typeof event.payload.runId === 'string' ? event.payload.runId : undefined
    if (runId) keys.push(['investigation-run', runId])
    if (runId && (event.type === 'investigation.checkpointed' || event.type === 'investigation.runtime_recovered')) keys.push(['investigation-checkpoints', runId])
  }
  if (event.type.startsWith('plan.') || event.type.startsWith('step.')) {
    keys.push(['plans', event.incidentId], ['dashboard'])
  }
  if (event.type.startsWith('alert.')) {
    keys.push(['alerts'])
  }
  if (event.type === 'approval.requested' || event.type === 'approval.resolved') {
    keys.push(['approvals'])
  }
  if (event.type === 'action.requested' || event.type === 'action.cancelled') {
    keys.push(['actions'])
  }
  if (event.type === 'action.proposal_created' || event.type === 'action.proposal_resolved') {
    keys.push(['action-proposals'])
  }
  if (event.type === 'resource_lock.acquired' || event.type === 'resource_lock.released') {
    keys.push(['resource-locks'])
  }
  if (['action.dispatched', 'action.started', 'action.succeeded', 'action.failed', 'action.unknown', 'action.reconciled'].includes(event.type)) {
    keys.push(['actions'])
    const actionId = typeof event.payload.actionId === 'string' ? event.payload.actionId : undefined
    if (actionId) keys.push(['action-execution', actionId])
    if (event.type === 'action.reconciled') keys.push(['resource-locks'])
  }
  if (['action.verification_queued', 'action.verification_passed', 'action.verification_failed'].includes(event.type)) {
    keys.push(['actions'])
    const actionId = typeof event.payload.actionId === 'string' ? event.payload.actionId : undefined
    if (actionId) keys.push(['action-verification', actionId])
    keys.push(['runner-tasks', { incidentId: event.incidentId }], ['incident-evidence', event.incidentId], ['resource-locks'])
  }
  if (event.type.startsWith('compensation.')) {
    keys.push(['actions'], ['compensations'])
    const compensationId = typeof event.payload.compensationId === 'string' ? event.payload.compensationId : undefined
    if (compensationId) keys.push(['compensation-execution', compensationId])
    if (event.type === 'compensation.succeeded' || event.type === 'compensation.escalated' || event.type === 'compensation.unknown') keys.push(['resource-locks'])
  }
  if (event.type.startsWith('runner_task.')) {
    keys.push(['runner-tasks', { incidentId: event.incidentId }])
  }
  if (event.type === 'runner_task.cancelled') {
    keys.push(['plans', event.incidentId], ['dashboard'])
  }
  if (event.type === 'runner_task.succeeded') {
    keys.push(['incident-evidence', event.incidentId])
  }
  return keys
}

export function evidenceIdForAgentEvent(event: AgentEventDto): string | undefined {
  if (event.type !== 'runner_task.succeeded') return undefined
  return typeof event.payload.evidenceId === 'string' && event.payload.evidenceId ? event.payload.evidenceId : undefined
}
