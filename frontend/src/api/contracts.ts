import type { AlertStatus, HypothesisStatus, InvestigationRunStatus, RunnerCapability, RunnerStatus, RunnerTaskStatus, Severity } from '../domain/types'
import type { components } from './generated/schema'

export interface InvestigationRunDto {
  id: string
  incidentId: string
  threadId: string
  status: InvestigationRunStatus
  graphVersion: string
  currentNode: string | null
  iterationCount: number
  maxIterations: number
  lastCheckpointSequence: number
  startedAt: string | null
  completedAt: string | null
  lastErrorCode: string | null
  runtimeAttempt: number
  modelRequestLimit: number
  modelRequestsUsed: number
  modelInputTokensUsed: number
  modelOutputTokensUsed: number
  version: number
  createdAt: string
  updatedAt: string
}

export interface InvestigationCheckpointDto {
  id: string
  runId: string
  sequence: number
  nodeExecutionId: string
  node: string
  graphVersion: string
  iteration: number
  planStepId: string | null
  hypothesisIds: string[]
  evidenceIds: string[]
  completedNodeKeys: string[]
  noProgressCount: number
  progressed: boolean
  nextAction: string | null
  modelRequests: number
  modelInputTokens: number
  modelOutputTokens: number
  outputSummary: string | null
  createdAt: string
}

export type InvestigationHitlWaitDto = components['schemas']['InvestigationHITLWaitResponse']

export interface HypothesisSummaryDto {
  id: string
  ordinal: number
  summary: string
  confidence: number
  status: HypothesisStatus
}

export interface HypothesisDto extends HypothesisSummaryDto {
  incidentId: string
  supportingEvidenceIds: string[]
  contradictingEvidenceIds: string[]
  version: number
  createdAt: string
  updatedAt: string
}

export interface RunnerTaskDto {
  id: string
  incidentId: string
  planStepId: string | null
  resourceId: string
  runnerId: string | null
  connector: string
  operation: string
  status: RunnerTaskStatus
  idempotencyKey: string
  timeoutSeconds: number
  maxAttempts: number
  attempt: number
  leaseExpiresAt: string | null
  taskFencingToken: number | null
  evidenceId: string | null
  resultSummary: string | null
  errorCode: string | null
  outputTruncated: boolean
  completedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface EvidenceDto {
  id: string
  incidentId: string
  resourceId: string | null
  evidenceType: string
  source: string
  summary: string
  contentHash: string
  redacted: boolean
  observedFrom: string | null
  observedTo: string | null
  collectedAt: string | null
  collectionStatus: 'succeeded' | 'partial' | 'failed'
  timeConfidence: 'runner_reported' | 'source_timestamp' | 'control_plane'
  data: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

export interface RunnerDto {
  id: string
  name: string
  status: RunnerStatus
  softwareVersion: string
  environmentId: string | null
  capabilities: RunnerCapability[]
  labels: Record<string, string>
  lastSeenAt: string
  leaseExpiresAt: string
  version: number
  createdAt: string
  updatedAt: string
}

export interface AlertDto {
  id: string
  source: string
  fingerprint: string
  status: AlertStatus
  severity: Severity
  title: string
  labels: Record<string, string>
  annotations: Record<string, string>
  startsAt: string
  endsAt: string | null
  receivedAt: string
  lastSeenAt: string
  occurrenceCount: number
  generatorUrl: string | null
  resourceId: string | null
  incidentId: string | null
}

export type IncidentDto = components['schemas']['IncidentResponse']

export interface PlanStepDto {
  id: string
  ordinal: number
  title: string
  objective: string
  kind: 'observe' | 'analyze' | 'experiment' | 'remediate' | 'verify' | 'human'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'blocked'
  risk: 'read_only' | 'low' | 'medium' | 'high'
  attempts: number
  evidenceIds: string[]
  resultSummary: string | null
  version: number
  createdAt: string
  updatedAt: string
}

export interface PlanDto {
  id: string
  incidentId: string
  version: number
  objective: string
  status: 'draft' | 'active' | 'completed' | 'superseded' | 'failed'
  maxToolCalls: number
  maxDurationSeconds: number
  replanCount: number
  steps: PlanStepDto[]
  createdAt: string
  updatedAt: string
}

export interface IncidentEventDto {
  id: string
  type: string
  occurredAt: string
  actorType: string
  actorId: string | null
  payload: Record<string, unknown>
}

export type IncidentDetailDto = components['schemas']['IncidentDetailResponse']
export type DashboardDto = components['schemas']['DashboardResponse']

export interface AgentEventDto {
  id: string
  sequence: number
  type: string
  incidentId: string
  traceId: string
  version: number
  occurredAt: string
  payload: Record<string, unknown>
}
