import type { components } from './generated/schema'
import { getJson, getPaginatedJson, postJson, type PaginatedResult } from './httpClient'

export type Compensation = components['schemas']['CompensationResponse']
export type CompensationStatus = components['schemas']['CompensationStatus']
export type CompensationCreate = components['schemas']['CompensationCreate']
export type CompensationDecision = components['schemas']['CompensationDecision']
export type CompensationDispatch = components['schemas']['CompensationDispatch']
export type CompensationEscalate = components['schemas']['CompensationEscalate']
export type CompensationExecution = components['schemas']['CompensationExecutionResponse']

export interface CompensationFilters { incidentId?: string; limit?: number; offset?: number }

export function buildCompensationPath(filters: CompensationFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.incidentId) query.set('incidentId', filters.incidentId)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/compensations${suffix ? `?${suffix}` : ''}`
}

export const compensationApi = {
  list(filters: CompensationFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<Compensation>> {
    return getPaginatedJson<Compensation>(buildCompensationPath(filters), signal)
  },
  create(actionId: string, body: CompensationCreate, signal?: AbortSignal): Promise<Compensation> {
    return postJson<CompensationCreate, Compensation>(`/actions/${actionId}/compensation`, body, signal)
  },
  decide(id: string, body: CompensationDecision, signal?: AbortSignal): Promise<Compensation> {
    return postJson<CompensationDecision, Compensation>(`/compensations/${id}/decision`, body, signal)
  },
  dispatch(id: string, body: CompensationDispatch, signal?: AbortSignal): Promise<CompensationExecution> {
    return postJson<CompensationDispatch, CompensationExecution>(`/compensations/${id}/dispatch`, body, signal)
  },
  execution(id: string, signal?: AbortSignal): Promise<CompensationExecution> {
    return getJson<CompensationExecution>(`/compensations/${id}/execution`, signal)
  },
  escalate(id: string, body: CompensationEscalate, signal?: AbortSignal): Promise<Compensation> {
    return postJson<CompensationEscalate, Compensation>(`/compensations/${id}/escalate`, body, signal)
  },
}
