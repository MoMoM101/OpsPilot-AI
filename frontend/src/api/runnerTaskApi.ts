import type { RunnerTask, RunnerTaskStatus } from '../domain/types'
import type { RunnerTaskDto } from './contracts'
import { getPaginatedJson, postJson, type PaginatedResult } from './httpClient'

export type RunnerTaskCreate = {
  incidentId: string
  planStepId?: string
  resourceId: string
  idempotencyKey: string
  timeoutSeconds?: number
  maxAttempts?: number
} & (
  | { connector: 'file'; operation: 'file.tail'; parameters: { path: string; lines: number } }
  | { connector: 'journal'; operation: 'journal.query'; parameters: { unit: string; lines: number; sinceMinutes: number; priority: number } }
  | { connector: 'http'; operation: 'http.probe'; parameters: { url: string; method: 'GET' | 'HEAD'; expectedStatuses: number[]; captureBody: boolean } }
  | { connector: 'tcp'; operation: 'tcp.probe'; parameters: { host: string; port: number } }
  | { connector: 'prometheus'; operation: 'prometheus.query'; parameters: { baseUrl: string; query: string } }
  | { connector: 'prometheus'; operation: 'prometheus.query_range'; parameters: { baseUrl: string; query: string; start: string; end: string; stepSeconds: number } }
  | { connector: 'host'; operation: 'host.snapshot'; parameters: Record<string, never> }
  | { connector: 'sqlite'; operation: 'sqlite.health' | 'sqlite.lock_status' | 'sqlite.integrity_check'; parameters: { path: string } }
  | { connector: 'qdrant'; operation: 'qdrant.health'; parameters: { baseUrl: string } }
  | { connector: 'qdrant'; operation: 'qdrant.collection' | 'qdrant.point_count'; parameters: { baseUrl: string; collection: string } }
  | { connector: 'qdrant'; operation: 'qdrant.query_smoke'; parameters: { baseUrl: string; collection: string; vector: number[]; limit?: number } }
  | { connector: 'rag'; operation: 'rag.business_health'; parameters: { url: string; question: string; expectedTerms?: string[] } }
)

export interface RunnerTaskFilters {
  status?: RunnerTaskStatus
  incidentId?: string
  planStepId?: string
  runnerId?: string
  limit?: number
  offset?: number
}

export function buildRunnerTaskPath(filters: RunnerTaskFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.incidentId) query.set('incident_id', filters.incidentId)
  if (filters.planStepId) query.set('plan_step_id', filters.planStepId)
  if (filters.runnerId) query.set('runner_id', filters.runnerId)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/runner-tasks${suffix ? `?${suffix}` : ''}`
}

export const runnerTaskApi = {
  async tasks(filters: RunnerTaskFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<RunnerTask>> {
    return getPaginatedJson<RunnerTaskDto>(buildRunnerTaskPath(filters), signal)
  },
  async create(body: RunnerTaskCreate, signal?: AbortSignal): Promise<RunnerTask> {
    return postJson<RunnerTaskCreate, RunnerTaskDto>('/runner-tasks', body, signal)
  },
}
