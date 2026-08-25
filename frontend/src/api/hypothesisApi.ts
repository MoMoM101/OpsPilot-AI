import type { Hypothesis, HypothesisStatus } from '../domain/types'
import type { HypothesisDto } from './contracts'
import { getPaginatedJson, patchJson, postJson, type PaginatedResult } from './httpClient'

export interface HypothesisFilters {
  limit?: number
  offset?: number
}

export interface HypothesisCreate {
  summary: string
  confidence: number
  supportingEvidenceIds?: string[]
  contradictingEvidenceIds?: string[]
}

export interface HypothesisUpdate {
  expectedVersion: number
  summary?: string
  confidence?: number
  status?: HypothesisStatus
  supportingEvidenceIds?: string[]
  contradictingEvidenceIds?: string[]
}

const incidentPath = (incidentId: string) => `/incidents/${encodeURIComponent(incidentId)}/hypotheses`

export function buildHypothesisPath(incidentId: string, filters: HypothesisFilters = {}) {
  const query = new URLSearchParams()
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `${incidentPath(incidentId)}${suffix ? `?${suffix}` : ''}`
}

export const hypothesisApi = {
  async forIncident(incidentId: string, filters: HypothesisFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<Hypothesis>> {
    return getPaginatedJson<HypothesisDto>(buildHypothesisPath(incidentId, filters), signal)
  },
  async create(incidentId: string, body: HypothesisCreate, signal?: AbortSignal): Promise<Hypothesis> {
    return postJson<HypothesisCreate, HypothesisDto>(incidentPath(incidentId), body, signal)
  },
  async update(incidentId: string, hypothesisId: string, body: HypothesisUpdate, signal?: AbortSignal): Promise<Hypothesis> {
    return patchJson<HypothesisUpdate, HypothesisDto>(`${incidentPath(incidentId)}/${encodeURIComponent(hypothesisId)}`, body, signal)
  },
}
