import type { components } from './generated/schema'
import { getPaginatedJson, type PaginatedResult } from './httpClient'

export type AuditRecord = components['schemas']['AuditRecordResponse']

export interface AuditFilters {
  actorId?: string
  action?: string
  outcome?: string
  from?: string
  to?: string
  limit?: number
  offset?: number
}

export function buildAuditPath(filters: AuditFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.actorId) query.set('actorId', filters.actorId)
  if (filters.action) query.set('action', filters.action)
  if (filters.outcome) query.set('outcome', filters.outcome)
  if (filters.from) query.set('from', filters.from)
  if (filters.to) query.set('to', filters.to)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/audit-logs${suffix ? `?${suffix}` : ''}`
}

export const auditApi = {
  list: (filters: AuditFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<AuditRecord>> =>
    getPaginatedJson<AuditRecord>(buildAuditPath(filters), signal),
}
