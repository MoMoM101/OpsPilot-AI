import type { components } from './generated/schema'
import { getJson, postJsonWithBearer } from './httpClient'

export type SetupStatus = components['schemas']['SetupStatusResponse']
export type InitialAdmin = components['schemas']['PrincipalCreateResponse']

const initialAdminBody: Omit<components['schemas']['PrincipalCreate'], 'name'> = {
  kind: 'user',
  role: 'admin',
  environmentIds: [],
  unrestrictedEnvironments: true,
}

export const setupApi = {
  status: (signal?: AbortSignal) => getJson<SetupStatus>('/setup/status', signal),
  createInitialAdmin: (name: string, bootstrapToken: string, signal?: AbortSignal) =>
    postJsonWithBearer<components['schemas']['PrincipalCreate'], InitialAdmin>('/principals', { ...initialAdminBody, name }, bootstrapToken, signal),
}
