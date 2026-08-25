import type { Evidence } from '../domain/types'
import type { EvidenceDto } from './contracts'
import { getJson, getPaginatedJson, type PaginatedResult } from './httpClient'

export interface EvidenceFilters {
  evidenceType?: string
  resourceId?: string
  limit?: number
  offset?: number
}

export function buildIncidentEvidencePath(incidentId: string, filters: EvidenceFilters = {}) {
  const query = new URLSearchParams()
  if (filters.evidenceType) query.set('evidence_type', filters.evidenceType)
  if (filters.resourceId) query.set('resource_id', filters.resourceId)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/incidents/${encodeURIComponent(incidentId)}/evidence${suffix ? `?${suffix}` : ''}`
}

export const evidenceApi = {
  async detail(evidenceId: string, signal?: AbortSignal): Promise<Evidence> {
    return getJson<EvidenceDto>(`/evidence/${encodeURIComponent(evidenceId)}`, signal)
  },
  async forIncident(incidentId: string, filters: EvidenceFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<Evidence>> {
    return getPaginatedJson<EvidenceDto>(buildIncidentEvidencePath(incidentId, filters), signal)
  },
}
