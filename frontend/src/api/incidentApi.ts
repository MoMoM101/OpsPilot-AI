import type { DashboardSummary, Incident, IncidentDetail } from '../domain/types'
import type { DashboardDto, IncidentDetailDto, IncidentDto, IncidentEventDto } from './contracts'
import { getJson, getPaginatedJson, type PaginatedResult } from './httpClient'
import { mapDashboard, mapIncident, mapIncidentDetail, mapTimelineEvent } from './mappers'

export interface IncidentTimelineFilters {
  limit?: number
  offset?: number
}

export function buildIncidentTimelinePath(incidentId: string, filters: IncidentTimelineFilters = {}): string {
  const params = new URLSearchParams()
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const query = params.toString()
  return `/incidents/${encodeURIComponent(incidentId)}/timeline${query ? `?${query}` : ''}`
}

export interface IncidentFilters {
  status?: import('../domain/types').IncidentStatus
  severity?: import('../domain/types').Severity
  environmentId?: string
  q?: string
  limit?: number
  offset?: number
}

export function buildIncidentListPath(filters: IncidentFilters = {}) {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.severity) params.set('severity', filters.severity)
  if (filters.environmentId) params.set('environmentId', filters.environmentId)
  if (filters.q) params.set('q', filters.q)
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const query = params.toString()
  return `/incidents${query ? `?${query}` : ''}`
}

export const incidentApi = {
  async dashboard(signal?: AbortSignal): Promise<DashboardSummary> {
    return mapDashboard(await getJson<DashboardDto>('/dashboard', signal))
  },
  async incidents(filters: IncidentFilters = {}, signal?: AbortSignal): Promise<Incident[]> {
    return (await getJson<IncidentDto[]>(buildIncidentListPath(filters), signal)).map(mapIncident)
  },
  async incidentPage(filters: IncidentFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<Incident>> {
    const page = await getPaginatedJson<IncidentDto>(buildIncidentListPath(filters), signal)
    return { ...page, items: page.items.map(mapIncident) }
  },
  async incident(id: string, signal?: AbortSignal): Promise<IncidentDetail> {
    return mapIncidentDetail(await getJson<IncidentDetailDto>(`/incidents/${encodeURIComponent(id)}`, signal))
  },
  async timeline(incidentId: string, filters: IncidentTimelineFilters = {}, signal?: AbortSignal): Promise<PaginatedResult<import('../domain/types').TimelineEvent>> {
    const page = await getPaginatedJson<IncidentEventDto>(buildIncidentTimelinePath(incidentId, filters), signal)
    return { ...page, items: page.items.map(mapTimelineEvent) }
  },
}
