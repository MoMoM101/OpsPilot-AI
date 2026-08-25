import type { InvestigationCheckpoint, InvestigationHitlWait, InvestigationRun } from '../domain/types'
import type { InvestigationCheckpointDto, InvestigationHitlWaitDto, InvestigationRunDto } from './contracts'
import { getJson, getPaginatedJson, postJson, type PaginatedResult } from './httpClient'

export interface InvestigationRunFilters { limit?: number; offset?: number }
export interface InvestigationCheckpointFilters { afterSequence?: number; limit?: number }
export interface InvestigationHitlWaitFilters { limit?: number; offset?: number }
export interface InvestigationRunCreate {
  idempotencyKey: string
  graphVersion?: 'graph-v1'
  maxIterations?: number
  maxModelRequests?: number
}

function queryString(values: Record<string, number | undefined>) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== undefined) query.set(key, String(value))
  const suffix = query.toString()
  return suffix ? `?${suffix}` : ''
}

export const investigationApi = {
  async create(incidentId: string, body: InvestigationRunCreate, signal?: AbortSignal): Promise<InvestigationRun> {
    return postJson<InvestigationRunCreate, InvestigationRunDto>(`/incidents/${encodeURIComponent(incidentId)}/investigation-runs`, body, signal)
  },
  async forIncident(incidentId: string, filters: InvestigationRunFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<InvestigationRun>> {
    const query = queryString({ limit: filters.limit, offset: filters.offset })
    return getPaginatedJson<InvestigationRunDto>(`/incidents/${encodeURIComponent(incidentId)}/investigation-runs${query}`, signal)
  },
  async detail(runId: string, signal?: AbortSignal): Promise<InvestigationRun> {
    return getJson<InvestigationRunDto>(`/investigation-runs/${encodeURIComponent(runId)}`, signal)
  },
  async checkpoints(runId: string, filters: InvestigationCheckpointFilters = {}, signal?: AbortSignal): Promise<InvestigationCheckpoint[]> {
    const query = queryString({ after_sequence: filters.afterSequence, limit: filters.limit })
    return getJson<InvestigationCheckpointDto[]>(`/investigation-runs/${encodeURIComponent(runId)}/checkpoints${query}`, signal)
  },
  async hitlWaits(runId: string, filters: InvestigationHitlWaitFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<InvestigationHitlWait>> {
    const query = queryString({ limit: filters.limit, offset: filters.offset })
    return getPaginatedJson<InvestigationHitlWaitDto>(`/investigation-runs/${encodeURIComponent(runId)}/hitl-waits${query}`, signal)
  },
}
