import { queryOptions } from '@tanstack/react-query'
import { alertApi, type AlertFilters } from './alertApi'
import { dataApi } from './dataApi'
import { mockApi } from './mockApi'
import { runnerApi, type RunnerFilters } from './runnerApi'
import { runnerTaskApi, type RunnerTaskFilters } from './runnerTaskApi'
import { evidenceApi, type EvidenceFilters } from './evidenceApi'
import { hypothesisApi, type HypothesisFilters } from './hypothesisApi'
import { planApi } from './planApi'
import { investigationApi, type InvestigationCheckpointFilters, type InvestigationHitlWaitFilters, type InvestigationRunFilters } from './investigationApi'
import { incidentApi, type IncidentFilters, type IncidentTimelineFilters } from './incidentApi'
import { adminApi, type AdminListFilters } from './adminApi'
import { policyApi, type PolicyFilters } from './policyApi'
import { approvalApi, type ApprovalFilters } from './approvalApi'
import { actionApi, type ActionFilters } from './actionApi'
import { resourceLockApi, type ResourceLockFilters } from './resourceLockApi'
import { compensationApi, type CompensationFilters } from './compensationApi'
import { actionProposalApi, type ActionProposalFilters } from './actionProposalApi'
import { connectorApi, type EnvironmentFilters } from './connectorApi'
import { resourceApi, type ResourceFilters } from './resourceApi'

export const dashboardQuery = queryOptions({ queryKey: ['dashboard'], queryFn: ({ signal }) => dataApi.dashboard(signal), staleTime: 15_000 })
export const incidentsQuery = queryOptions({ queryKey: ['incidents'], queryFn: ({ signal }) => dataApi.incidents({}, signal), staleTime: 15_000 })
export const filteredIncidentsQuery = (filters: IncidentFilters = {}) => queryOptions({
  queryKey: ['incidents', 'list', filters],
  queryFn: ({ signal }) => dataApi.incidents(filters, signal),
  staleTime: 15_000,
})
export const filteredIncidentsPageQuery = (filters: IncidentFilters = {}) => queryOptions({
  queryKey: ['incidents', 'page', filters],
  queryFn: ({ signal }) => incidentApi.incidentPage(filters, signal),
  staleTime: 15_000,
})
export const incidentQuery = (id: string) => queryOptions({ queryKey: ['incidents', id], queryFn: ({ signal }) => dataApi.incident(id, signal), staleTime: 10_000 })
export const INCIDENT_TIMELINE_PAGE_SIZE = 100
export const incidentTimelinePageQuery = (incidentId: string, filters: IncidentTimelineFilters = { limit: INCIDENT_TIMELINE_PAGE_SIZE, offset: 0 }) => queryOptions({
  queryKey: ['incident-timeline', incidentId, filters],
  queryFn: ({ signal }) => incidentApi.timeline(incidentId, filters, signal),
  staleTime: 10_000,
})
export const actionProposalsQuery = (filters: ActionProposalFilters = {}) => queryOptions({
  queryKey: ['action-proposals', filters],
  queryFn: ({ signal }) => actionProposalApi.list(filters, signal),
  staleTime: 10_000,
})
export const investigationRunsQuery = (incidentId: string, filters: InvestigationRunFilters = {}) => queryOptions({
  queryKey: ['investigation-runs', incidentId, filters],
  queryFn: ({ signal }) => investigationApi.forIncident(incidentId, filters, signal),
  staleTime: 10_000,
})
export const investigationRunQuery = (runId: string) => queryOptions({
  queryKey: ['investigation-run', runId],
  queryFn: ({ signal }) => investigationApi.detail(runId, signal),
  staleTime: 10_000,
})
export const investigationCheckpointsQuery = (runId: string, filters: InvestigationCheckpointFilters = {}) => queryOptions({
  queryKey: ['investigation-checkpoints', runId, filters],
  queryFn: ({ signal }) => investigationApi.checkpoints(runId, filters, signal),
  staleTime: 10_000,
})
export const investigationHitlWaitsQuery = (runId: string, filters: InvestigationHitlWaitFilters = {}) => queryOptions({
  queryKey: ['investigation-hitl-waits', runId, filters],
  queryFn: ({ signal }) => investigationApi.hitlWaits(runId, filters, signal),
  staleTime: 10_000,
})
export const currentPlanQuery = (incidentId: string) => queryOptions({
  queryKey: ['plans', incidentId],
  queryFn: ({ signal }) => planApi.current(incidentId, signal),
  staleTime: 10_000,
})
export const hypothesesQuery = (incidentId: string, filters: HypothesisFilters = {}) => queryOptions({
  queryKey: ['hypotheses', incidentId, filters],
  queryFn: ({ signal }) => hypothesisApi.forIncident(incidentId, filters, signal),
  staleTime: 10_000,
})
export const mockActionQuery = queryOptions({ queryKey: ['demo', 'actions', 'active'], queryFn: mockApi.action, staleTime: 5_000 })
export const alertsQuery = (filters: AlertFilters = {}) => queryOptions({
  queryKey: ['alerts', filters],
  queryFn: ({ signal }) => alertApi.alerts(filters, signal),
  staleTime: 10_000,
})
export const alertsPageQuery = (filters: AlertFilters = {}) => queryOptions({
  queryKey: ['alerts', 'page', filters],
  queryFn: ({ signal }) => alertApi.page(filters, signal),
  staleTime: 10_000,
})
export const runnersQuery = (filters: RunnerFilters = {}) => queryOptions({
  queryKey: ['runners', filters],
  queryFn: ({ signal }) => runnerApi.runners(filters, signal),
  staleTime: 10_000,
  refetchInterval: 15_000,
})
export const environmentsQuery = (filters: EnvironmentFilters = {}) => queryOptions({
  queryKey: ['environments', filters],
  queryFn: ({ signal }) => connectorApi.environments(filters, signal),
  staleTime: 30_000,
})
export const allEnvironmentsQuery = queryOptions({
  queryKey: ['environments', 'all'],
  queryFn: ({ signal }) => connectorApi.allEnvironments(signal),
  staleTime: 30_000,
})
export const resourcesQuery = (filters: ResourceFilters = {}) => queryOptions({
  queryKey: ['resources', filters],
  queryFn: ({ signal }) => resourceApi.list(filters, signal),
  staleTime: 15_000,
})
export const connectorCatalogQuery = (environmentId?: string) => queryOptions({
  queryKey: ['connectors', environmentId ?? 'authorized-scope'],
  queryFn: ({ signal }) => connectorApi.catalog(environmentId, signal),
  staleTime: 10_000,
})
export const runnerTasksQuery = (filters: RunnerTaskFilters = {}) => queryOptions({
  queryKey: ['runner-tasks', filters],
  queryFn: ({ signal }) => runnerTaskApi.tasks(filters, signal),
  staleTime: 10_000,
})
export const evidenceDetailQuery = (evidenceId: string) => queryOptions({
  queryKey: ['evidence', evidenceId],
  queryFn: ({ signal }) => evidenceApi.detail(evidenceId, signal),
  staleTime: 60_000,
})
export const incidentEvidenceQuery = (incidentId: string, filters: EvidenceFilters = {}) => queryOptions({
  queryKey: ['incident-evidence', incidentId, filters],
  queryFn: ({ signal }) => evidenceApi.forIncident(incidentId, filters, signal),
  staleTime: 10_000,
})
export const principalsQuery = (filters: AdminListFilters = {}) => queryOptions({ queryKey: ['principals', filters], queryFn: ({ signal }) => adminApi.principals(filters, signal), staleTime: 15_000 })
export const outboxStatusQuery = queryOptions({ queryKey: ['outbox', 'status'], queryFn: ({ signal }) => adminApi.outboxStatus(signal), staleTime: 5_000, refetchInterval: 10_000 })
export const outboxDeadLettersQuery = (filters: AdminListFilters = {}) => queryOptions({ queryKey: ['outbox', 'dead-letters', filters], queryFn: ({ signal }) => adminApi.deadLetters(filters, signal), staleTime: 5_000 })
export const policyRulesQuery = (filters: PolicyFilters) => queryOptions({
  queryKey: ['policies', filters],
  queryFn: ({ signal }) => policyApi.rules(filters, signal),
  staleTime: 10_000,
})
export const approvalsQuery = (filters: ApprovalFilters = {}) => queryOptions({
  queryKey: ['approvals', filters],
  queryFn: ({ signal }) => approvalApi.list(filters, signal),
  staleTime: 10_000,
})
export const approvalsPageQuery = (filters: ApprovalFilters = {}) => queryOptions({
  queryKey: ['approvals', 'page', filters],
  queryFn: ({ signal }) => approvalApi.page(filters, signal),
  staleTime: 10_000,
})
export const actionsQuery = (filters: ActionFilters = {}) => queryOptions({
  queryKey: ['actions', filters],
  queryFn: ({ signal }) => actionApi.list(filters, signal),
  staleTime: 10_000,
})
export const actionCapabilitiesQuery = queryOptions({
  queryKey: ['action-capabilities'],
  queryFn: ({ signal }) => actionApi.capabilities(signal),
  staleTime: 5 * 60_000,
})
export const actionsPageQuery = (filters: ActionFilters = {}) => queryOptions({
  queryKey: ['actions', 'page', filters],
  queryFn: ({ signal }) => actionApi.page(filters, signal),
  staleTime: 10_000,
})
export const actionExecutionQuery = (actionId: string) => queryOptions({
  queryKey: ['action-execution', actionId],
  queryFn: ({ signal }) => actionApi.execution(actionId, signal),
  staleTime: 5_000,
  retry: false,
})
export const actionVerificationQuery = (actionId: string) => queryOptions({
  queryKey: ['action-verification', actionId],
  queryFn: ({ signal }) => actionApi.verification(actionId, signal),
  staleTime: 5_000,
  retry: false,
})
export const resourceLocksQuery = (filters: ResourceLockFilters = {}) => queryOptions({
  queryKey: ['resource-locks', filters],
  queryFn: ({ signal }) => resourceLockApi.list(filters, signal),
  staleTime: 10_000,
  refetchInterval: 10_000,
})
export const compensationsQuery = (filters: CompensationFilters = {}) => queryOptions({
  queryKey: ['compensations', filters],
  queryFn: ({ signal }) => compensationApi.list(filters, signal),
  staleTime: 5_000,
})
export const compensationExecutionQuery = (id: string) => queryOptions({
  queryKey: ['compensation-execution', id],
  queryFn: ({ signal }) => compensationApi.execution(id, signal),
  staleTime: 5_000,
  retry: false,
})
