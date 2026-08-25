import type { components } from './generated/schema'
import { getJson, postJson } from './httpClient'

export type LabScenario = components['schemas']['LabScenarioResponse']
export type LabScenarioMutationRequest = components['schemas']['LabScenarioMutationRequest']
export type LabScenarioMutationResponse = components['schemas']['LabScenarioMutationResponse']

export type LabScenarioAction = 'inject' | 'cleanup'

export function buildLabMutationPath(scenarioId: string, action: LabScenarioAction): string {
  return `/lab/scenarios/${encodeURIComponent(scenarioId)}/${action}`
}

export const labApi = {
  list(signal?: AbortSignal): Promise<LabScenario[]> {
    return getJson<LabScenario[]>('/lab/scenarios', signal)
  },
  mutate(
    scenarioId: string,
    action: LabScenarioAction,
    body: LabScenarioMutationRequest,
    signal?: AbortSignal,
  ): Promise<LabScenarioMutationResponse> {
    return postJson<LabScenarioMutationRequest, LabScenarioMutationResponse>(
      buildLabMutationPath(scenarioId, action),
      body,
      signal,
    )
  },
}
