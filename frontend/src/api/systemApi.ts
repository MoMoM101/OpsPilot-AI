import type { components } from './generated/schema'
import { getJson, postJsonWithoutBody } from './httpClient'

export type DeploymentPreflight = components['schemas']['DeploymentPreflightResponse']
export type DeploymentPreflightCheck = components['schemas']['DeploymentPreflightCheckResponse']
export type ModelConnectionCheck = components['schemas']['ModelConnectionCheckResponse']

export const systemApi = {
  preflight: (signal?: AbortSignal) => getJson<DeploymentPreflight>('/system/preflight', signal),
  checkModelConnection: (signal?: AbortSignal) => postJsonWithoutBody<ModelConnectionCheck>('/system/model-connection-check', signal),
}
