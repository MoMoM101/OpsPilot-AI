import { apiConfig } from './config'
import { incidentApi } from './incidentApi'
import { mockApi } from './mockApi'
import type { IncidentFilters } from './incidentApi'

export const dataApi = apiConfig.mocksEnabled
  ? {
      mode: 'mock' as const,
      dashboard: (_signal?: AbortSignal) => mockApi.dashboard(),
      incidents: async (filters: IncidentFilters = {}, _signal?: AbortSignal) => {
        const incidents = await mockApi.incidents()
        return incidents.filter((incident) =>
          (!filters.status || incident.status === filters.status)
          && (!filters.severity || incident.severity === filters.severity))
      },
      incident: (id: string, _signal?: AbortSignal) => mockApi.incident(id),
    }
  : {
      mode: 'http' as const,
      dashboard: incidentApi.dashboard,
      incidents: incidentApi.incidents,
      incident: incidentApi.incident,
    }
