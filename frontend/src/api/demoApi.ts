import type { components } from './generated/schema'
import { getJson, postJson, postJsonWithoutBody } from './httpClient'

export type DemoStatus = components['schemas']['DemoStatusResponse']
export type DemoInitializeResult = components['schemas']['DemoInitializeResponse']
export type DemoCleanupResult = components['schemas']['DemoCleanupResponse']

export const demoApi = {
  status: (signal?: AbortSignal) => getJson<DemoStatus>('/demo/status', signal),
  initialize: (signal?: AbortSignal) => postJsonWithoutBody<DemoInitializeResult>('/demo/initialize', signal),
  cleanup: (expectedGeneration: number, signal?: AbortSignal) =>
    postJson<components['schemas']['DemoCleanupRequest'], DemoCleanupResult>('/demo/cleanup', { expectedGeneration }, signal),
}
