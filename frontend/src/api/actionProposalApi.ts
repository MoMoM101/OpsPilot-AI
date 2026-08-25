import type { components } from './generated/schema'
import { getPaginatedJson, type PaginatedResult } from './httpClient'

export type ActionProposal = components['schemas']['ActionProposalResponse']
export type ActionProposalStatus = components['schemas']['ActionProposalStatus']

export interface ActionProposalFilters {
  incidentId?: string
  status?: ActionProposalStatus
  limit?: number
  offset?: number
}

export function buildActionProposalPath(filters: ActionProposalFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.incidentId) query.set('incident_id', filters.incidentId)
  if (filters.status) query.set('status', filters.status)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/action-proposals${suffix ? `?${suffix}` : ''}`
}

export const actionProposalApi = {
  list(filters: ActionProposalFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<ActionProposal>> {
    return getPaginatedJson<ActionProposal>(buildActionProposalPath(filters), signal)
  },
}
