import type { Alert, AlertStatus } from '../domain/types'
import type { AlertDto } from './contracts'
import { getJson, getPaginatedJson, type PaginatedResult } from './httpClient'

export interface AlertFilters {
  status?: AlertStatus
  resourceId?: string
  incidentId?: string
  limit?: number
  offset?: number
}

export function buildAlertPath(filters: AlertFilters = {}): string {
  const query = new URLSearchParams()
  if (filters.status) query.set('status', filters.status)
  if (filters.resourceId) query.set('resource_id', filters.resourceId)
  if (filters.incidentId) query.set('incident_id', filters.incidentId)
  if (filters.limit !== undefined) query.set('limit', String(filters.limit))
  if (filters.offset !== undefined) query.set('offset', String(filters.offset))
  const suffix = query.toString()
  return `/alerts${suffix ? `?${suffix}` : ''}`
}

export const alertApi = {
  async alerts(filters: AlertFilters = {}, signal?: AbortSignal): Promise<Alert[]> {
    return getJson<AlertDto[]>(buildAlertPath(filters), signal)
  },
  page(filters: AlertFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<Alert>> {
    return getPaginatedJson<AlertDto>(buildAlertPath(filters), signal)
  },
}
