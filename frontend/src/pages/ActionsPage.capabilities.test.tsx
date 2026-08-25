import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IncidentStreamContext } from '../components/IncidentStreamContext'
import { ActionsPage } from './ActionsPage'

vi.mock('@tanstack/react-router', () => ({ Link: ({ children }: { children: React.ReactNode }) => <a href="#">{children}</a> }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 'operator-1' } }) }))

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Action capability-driven form', () => {
  it('offers only available capabilities and generates the parameter field from metadata', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname.endsWith('/action-capabilities')) return Response.json({ contractVersion: '1.0', capabilities: [
        { capability: 'container.restart', availability: 'available', effect: 'mutation', recommendedRisk: 'medium', executionConnector: 'docker', approvalMode: 'policy', verificationCriteriaRequired: true, parameter: { key: 'containerId', valueType: 'string', required: true, minLength: 1, maxLength: 100, secret: false }, verification: { connector: 'docker', operation: 'docker.container_health', actionParameterKey: 'containerId', verificationParameterKey: 'containerId' }, compensation: { supported: false, mode: 'manual_escalation', capability: null } },
        { capability: 'health.check', availability: 'available', effect: 'observation', recommendedRisk: 'read_only', executionConnector: 'docker', approvalMode: 'policy', verificationCriteriaRequired: false, parameter: { key: 'target', valueType: 'string', required: true, minLength: 2, maxLength: 80, secret: false }, verification: null, compensation: { supported: false, mode: 'not_applicable', capability: null } },
        { capability: 'service.reload', availability: 'reserved', effect: 'mutation', recommendedRisk: 'medium', executionConnector: null, approvalMode: 'policy', verificationCriteriaRequired: true, parameter: { key: 'serviceName', valueType: 'string', required: true, minLength: 1, maxLength: 100, secret: false }, verification: null, compensation: { supported: false, mode: 'unavailable', capability: null } },
      ] })
      if (url.pathname.endsWith('/actions')) return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '0', 'X-Limit': '25', 'X-Offset': '0' } })
      if (url.pathname.endsWith('/resource-locks')) return new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Total-Count': '0', 'X-Limit': '100', 'X-Offset': '0' } })
      throw new Error(`Unexpected request: ${url.pathname}`)
    }))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><IncidentStreamContext.Provider value={{ setRequestedIncidentId: vi.fn() }}><ActionsPage /></IncidentStreamContext.Provider></QueryClientProvider>)

    const capabilitySelect = await screen.findByLabelText('Action 能力')
    await waitFor(() => expect(screen.getByLabelText(/^containerId/)).toBeInTheDocument())
    expect(Array.from((capabilitySelect as HTMLSelectElement).options).map((option) => option.value)).not.toContain('service.reload')
    expect(screen.getByText('service.reload')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Rollback Capability/i)).not.toBeInTheDocument()
    expect(screen.getByText(/最终风险以 Policy Decision 为准/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^验证标准/)).toBeRequired()

    fireEvent.change(capabilitySelect, { target: { value: 'health.check' } })

    expect(await screen.findByLabelText(/^target/)).toHaveAttribute('minlength', '2')
    expect(screen.getByLabelText(/^验证标准/)).not.toBeRequired()
  })
})
