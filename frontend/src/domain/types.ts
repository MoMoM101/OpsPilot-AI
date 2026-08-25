export type IncidentStatus =
  | 'DETECTED'
  | 'CORRELATING'
  | 'INVESTIGATING'
  | 'DIAGNOSED'
  | 'PLANNING'
  | 'WAITING_APPROVAL'
  | 'REMEDIATING'
  | 'VERIFYING'
  | 'RESOLVED'
  | 'CLOSED'
  | 'OBSERVABILITY_LOST'
  | 'NEEDS_HUMAN'
  | 'MITIGATED_NOT_RESOLVED'
  | 'FAILED'
  | 'CANCELLED'

export type ActionStatus =
  | 'PROPOSED'
  | 'AUTHORIZED'
  | 'WAITING_RESOURCE'
  | 'DISPATCHING'
  | 'APPLIED'
  | 'RECONCILING'
  | 'VERIFYING'
  | 'SUCCEEDED'
  | 'UNKNOWN'
  | 'VERIFICATION_FAILED'
  | 'COMPENSATING'
  | 'COMPENSATED'
  | 'ESCALATED'

export type Severity = 'critical' | 'high' | 'medium' | 'low'
export type AlertStatus = 'firing' | 'resolved'
export type RunnerStatus = 'online' | 'offline' | 'draining' | 'disabled'
export type RunnerTaskStatus = 'queued' | 'leased' | 'succeeded' | 'failed' | 'cancelled'
export type ResourceAccessMode = 'OBSERVE' | 'RESERVE' | 'MUTATE'
export type HypothesisStatus = 'proposed' | 'supported' | 'weakened' | 'rejected' | 'confirmed'
export type InvestigationRunStatus = 'queued' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
export type InvestigationHitlWaitStatus = 'waiting' | 'resolved' | 'cancelled'
export type InvestigationHitlSubjectType = 'approval' | 'compensation'

export interface InvestigationRun {
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

export interface InvestigationCheckpoint {
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

export interface InvestigationHitlWait {
  id: string
  runId: string
  incidentId: string
  checkpointId: string
  subjectType: InvestigationHitlSubjectType
  subjectId: string
  status: InvestigationHitlWaitStatus
  outcome: string | null
  resolvedAt: string | null
  resumedAt: string | null
  version: number
  createdAt: string
  updatedAt: string
}

export interface HypothesisSummary {
  id: string
  ordinal: number
  summary: string
  confidence: number
  status: HypothesisStatus
}

export interface Hypothesis extends HypothesisSummary {
  incidentId: string
  supportingEvidenceIds: string[]
  contradictingEvidenceIds: string[]
  version: number
  createdAt: string
  updatedAt: string
}

export interface RunnerCapability {
  connector?: string
  contractVersion?: string
  observe?: string[]
  actions?: string[]
  unsupported?: string[]
  [key: string]: unknown
}

export interface Runner {
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

export interface RunnerTask {
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

export interface Evidence {
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

export interface Alert {
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

export interface Incident {
  id: string
  title: string
  status: IncidentStatus
  severity: Severity
  resource: string
  resourceId: string
  environment: string
  owner?: string
  observabilityStatus: 'observable' | 'lost'
  observabilityRunnerId: string | null
  observabilityLostAt: string | null
  version: number
  createdAt: string
  updatedAt: string
  hypothesis?: HypothesisSummary
}

export interface TimelineEvent {
  id: string
  type: 'event' | 'plan' | 'tool' | 'decision'
  occurredAt: string
  title: string
  detail: string
}

export interface PlanStep {
  id: string
  ordinal: number
  title: string
  objective: string
  kind: 'observe' | 'analyze' | 'experiment' | 'verify' | 'remediate' | 'human'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'blocked'
  risk: 'read_only' | 'low' | 'medium' | 'high'
  attempts: number
  evidenceIds: string[]
  resultSummary?: string
  version: number
  createdAt: string
  updatedAt: string
}

export interface Plan {
  id: string
  incidentId: string
  version: number
  objective: string
  status: 'draft' | 'active' | 'completed' | 'superseded' | 'failed'
  maxToolCalls: number
  maxDurationSeconds: number
  replanCount: number
  steps: PlanStep[]
  createdAt: string
  updatedAt: string
}

export interface IncidentDetail extends Incident {
  traceId: string
  eventCursor: number
  timelineTotal: number
  timelineTruncated: boolean
  autonomyLevel: 'L0' | 'L1' | 'L2' | 'L3'
  planVersion: number
  replanCount: number
  toolBudget: { used: number; limit: number }
  steps: PlanStep[]
  timeline: TimelineEvent[]
}

export interface ResourceConflict {
  taskId: string
  action: string
  accessMode: ResourceAccessMode
  state: 'CURRENT' | 'WAITING_RESOURCE' | 'SHARED'
  resource: string
  detail: string
}

export interface ActionExecution {
  id: string
  incidentId: string
  approvalId: string
  title: string
  resource: string
  status: ActionStatus
  risk: 'low' | 'medium' | 'high'
  stages: ActionStatus[]
  fencingToken: number
  resourceVersion: number
  leaseSeconds: number
  verification: { passed: number; required: number; criterion: string }
  conflicts: ResourceConflict[]
}

export interface DashboardSummary {
  activeTasks: number
  waitingHuman: number
  rootCauseRate: number
  meanInvestigationSeconds: number
  runnerOnline: number
  runnerTotal: number
  safety: {
    pendingApprovals: number
    activeResourceLocks: number
    unknownActions: number
    actionsRequiringAttention: number
    observabilityLostIncidents: number
  }
  incidents: Incident[]
}

export type IncidentEvent =
  | { type: 'incident.updated'; incidentId: string; version: number }
  | { type: 'action.started'; incidentId: string; actionId: string }
  | { type: 'action.reconciled'; incidentId: string; actionId: string; result: 'APPLIED' | 'NOT_APPLIED' | 'UNKNOWN' }
  | { type: 'verification.completed'; incidentId: string; actionId: string; recovered: boolean }
  | { type: 'resource.locked'; resourceId: string; actionId: string; fencingToken: number }
  | { type: 'resource.released'; resourceId: string; actionId: string }
