import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DashboardPage } from './DashboardPage'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children }: { children: React.ReactNode }) => <a href="#">{children}</a>,
}))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ canWrite: false, user: { role: 'viewer', unrestrictedEnvironments: false, environmentIds: ['env-1'] } }),
}))

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Dashboard safety snapshot', () => {
  it('is visible to a restricted Viewer and renders the five scoped safety metrics without double counting UNKNOWN', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({
      activeTasks: 0,
      waitingHuman: 0,
      rootCauseRate: 0,
      meanInvestigationSeconds: 0,
      runnerOnline: 2,
      runnerTotal: 3,
      safety: { pendingApprovals: 4, activeResourceLocks: 5, unknownActions: 3, actionsRequiringAttention: 7, observabilityLostIncidents: 6 },
      incidents: [],
    })))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><DashboardPage /></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: 'Agent 运行总览' })).toBeInTheDocument()
    const runnerCard = screen.getByText('Runner 在线').closest('article') as HTMLElement
    expect(within(runnerCard).getByText('2/3')).toBeInTheDocument()
    expect(within(runnerCard).queryByText('暂未接入')).not.toBeInTheDocument()

    const safetyPanel = screen.getByRole('heading', { name: '运行安全' }).closest('.panel') as HTMLElement
    expect(within(safetyPanel).getByText('7')).toBeInTheDocument()
    expect(within(safetyPanel).getByText('3')).toBeInTheDocument()
    expect(within(safetyPanel).getByText('4')).toBeInTheDocument()
    expect(within(safetyPanel).getByText('5')).toBeInTheDocument()
    expect(within(safetyPanel).getByText('6')).toBeInTheDocument()
    expect(within(safetyPanel).queryByText('10')).not.toBeInTheDocument()
    expect(within(safetyPanel).queryByText('暂未接入')).not.toBeInTheDocument()
  })
})
