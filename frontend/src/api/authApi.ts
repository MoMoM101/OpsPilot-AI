import type { components } from './generated/schema'
import { deleteJson, getJson, postJson, postJsonWithoutBody } from './httpClient'

type PrincipalSession = components['schemas']['PrincipalSessionResponse']
type BrowserSession = components['schemas']['BrowserSessionResponse']

export const authApi = {
  me: (signal?: AbortSignal) => getJson<PrincipalSession>('/auth/me', signal),
  exchange: (accessToken: string, signal?: AbortSignal) =>
    postJson<components['schemas']['BrowserSessionCreate'], BrowserSession>('/auth/session', { accessToken }, signal),
  refresh: (signal?: AbortSignal) => postJsonWithoutBody<BrowserSession>('/auth/session/refresh', signal),
  logout: (signal?: AbortSignal) => deleteJson('/auth/session', signal),
}
