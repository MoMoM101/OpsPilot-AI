import type { Plan } from '../domain/types'
import type { PlanDto } from './contracts'
import { ApiError, getJson } from './httpClient'
import { mapPlanStep } from './mappers'

export const planApi = {
  async current(incidentId: string, signal?: AbortSignal): Promise<Plan | null> {
    try {
      const dto = await getJson<PlanDto>(`/incidents/${encodeURIComponent(incidentId)}/plans/current`, signal)
      return { ...dto, steps: dto.steps.map(mapPlanStep) }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404 && error.code === 'PLAN_NOT_FOUND') return null
      throw error
    }
  },
}
