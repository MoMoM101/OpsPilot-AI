import type { components } from './generated/schema'
import { getJson, getPaginatedJson, postJson, type PaginatedResult } from './httpClient'

export type Approval = components['schemas']['ApprovalResponse']
export type ApprovalStatus = components['schemas']['ApprovalStatus']
export type ApprovalDecisionRequest = components['schemas']['ApprovalDecisionRequest']
export type ApprovalParameter = components['schemas']['ApprovalParameter']

export interface ApprovalFilters {
  incidentId?: string
  status?: ApprovalStatus
  limit?: number
  offset?: number
}

export function buildApprovalPath(filters: ApprovalFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.incidentId) query.set('incidentId', filters.incidentId)
  if (filters.status) query.set('status', filters.status)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/approvals${suffix ? `?${suffix}` : ''}`
}

export const approvalApi = {
  list(filters: ApprovalFilters = {}, signal?: AbortSignal): Promise<Approval[]> {
    return getJson<Approval[]>(buildApprovalPath(filters), signal)
  },
  page(filters: ApprovalFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<Approval>> {
    return getPaginatedJson<Approval>(buildApprovalPath(filters), signal)
  },
  decide(approvalId: string, body: ApprovalDecisionRequest, signal?: AbortSignal): Promise<Approval> {
    return postJson<ApprovalDecisionRequest, Approval>(`/approvals/${approvalId}/decision`, body, signal)
  },
}
