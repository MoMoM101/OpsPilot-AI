import type { DashboardDto, IncidentDetailDto, IncidentDto, IncidentEventDto, PlanStepDto } from './contracts'
import type { DashboardSummary, Incident, IncidentDetail, PlanStep, TimelineEvent } from '../domain/types'

export function mapIncident(dto: IncidentDto): Incident {
  return {
    id: dto.id,
    title: dto.title,
    status: dto.status,
    severity: dto.severity,
    resource: dto.resource,
    resourceId: dto.resourceId,
    environment: dto.environment,
    owner: dto.owner ?? undefined,
    observabilityStatus: dto.observabilityStatus,
    observabilityRunnerId: dto.observabilityRunnerId,
    observabilityLostAt: dto.observabilityLostAt,
    hypothesis: dto.hypothesis ?? undefined,
    version: dto.version,
    createdAt: dto.createdAt,
    updatedAt: dto.updatedAt,
  }
}

function eventKind(type: string): TimelineEvent['type'] {
  if (type.startsWith('tool.')) return 'tool'
  if (type.startsWith('plan.') || type.startsWith('step.')) return 'plan'
  if (type.startsWith('hypothesis.') || type.includes('replan') || type.includes('decision')) return 'decision'
  return 'event'
}

function eventDetail(event: IncidentEventDto): string {
  const preferred = ['summary', 'message', 'resultSummary', 'reason']
  for (const key of preferred) {
    const value = event.payload[key]
    if (typeof value === 'string' && value) return value
  }
  const entries = Object.entries(event.payload)
  return entries.length ? entries.map(([key, value]) => `${key}=${String(value)}`).join(' · ') : `${event.actorType}${event.actorId ? `/${event.actorId}` : ''}`
}

export function mapTimelineEvent(event: IncidentEventDto): TimelineEvent {
  return {
    id: event.id,
    type: eventKind(event.type),
    occurredAt: new Date(event.occurredAt).toLocaleTimeString('zh-CN', { hour12: false }),
    title: event.type,
    detail: eventDetail(event),
  }
}

export function mapPlanStep(step: PlanStepDto): PlanStep {
  return {
    ...step,
    resultSummary: step.resultSummary ?? undefined,
  }
}

export function mapIncidentDetail(dto: IncidentDetailDto): IncidentDetail {
  return {
    ...mapIncident(dto),
    traceId: dto.traceId,
    eventCursor: dto.eventCursor,
    timelineTotal: dto.timelineTotal,
    timelineTruncated: dto.timelineTruncated,
    autonomyLevel: dto.autonomyLevel,
    planVersion: dto.planVersion,
    replanCount: dto.replanCount,
    toolBudget: dto.toolBudget,
    steps: dto.steps.map(mapPlanStep),
    timeline: dto.timeline.map(mapTimelineEvent),
  }
}

export function mapDashboard(dto: DashboardDto): DashboardSummary {
  const safety = dto.safety ?? {
    pendingApprovals: 0,
    activeResourceLocks: 0,
    unknownActions: 0,
    actionsRequiringAttention: 0,
    observabilityLostIncidents: 0,
  }
  return {
    activeTasks: dto.activeTasks,
    waitingHuman: dto.waitingHuman,
    rootCauseRate: dto.rootCauseRate,
    meanInvestigationSeconds: dto.meanInvestigationSeconds,
    runnerOnline: dto.runnerOnline,
    runnerTotal: dto.runnerTotal,
    safety,
    incidents: dto.incidents.map(mapIncident),
  }
}
