import { lazy, Suspense } from 'react'
import { createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { AuthRoot, RequireRole } from '../components/AuthRoot'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { ActionsPage } from '../pages/ActionsPage'
import { AlertsPage } from '../pages/AlertsPage'
import { DashboardPage } from '../pages/DashboardPage'
import { IncidentsPage } from '../pages/IncidentsPage'
import { PlaceholderPage } from '../pages/PlaceholderPage'
import { RunnersPage } from '../pages/RunnersPage'
import { ResourcesPage } from '../pages/ResourcesPage'
import type { IncidentStatus } from '../domain/types'
import { LoginPage } from '../pages/LoginPage'
import { PoliciesPage } from '../pages/PoliciesPage'
import { ApprovalsPage } from '../pages/ApprovalsPage'
import { SetupPage } from '../pages/SetupPage'

const IncidentDetailPage = lazy(() => import('../pages/IncidentDetailPage').then((module) => ({ default: module.IncidentDetailPage })))
const IncidentEvidencePage = lazy(() => import('../pages/IncidentEvidencePage').then((module) => ({ default: module.IncidentEvidencePage })))
const IncidentEvidenceDetailPage = lazy(() => import('../pages/IncidentEvidencePage').then((module) => ({ default: module.IncidentEvidenceDetailPage })))
const LogsPage = lazy(() => import('../pages/LogsPage').then((module) => ({ default: module.LogsPage })))
const ProbesPage = lazy(() => import('../pages/ProbesPage').then((module) => ({ default: module.ProbesPage })))
const PrometheusPage = lazy(() => import('../pages/PrometheusPage').then((module) => ({ default: module.PrometheusPage })))
const HostSnapshotsPage = lazy(() => import('../pages/HostSnapshotsPage').then((module) => ({ default: module.HostSnapshotsPage })))
const IdentityAdminPage = lazy(() => import('../pages/IdentityAdminPage').then((module) => ({ default: module.IdentityAdminPage })))
const OutboxAdminPage = lazy(() => import('../pages/OutboxAdminPage').then((module) => ({ default: module.OutboxAdminPage })))
const FaultLabPage = lazy(() => import('../pages/FaultLabPage').then((module) => ({ default: module.FaultLabPage })))
const SystemPreflightPage = lazy(() => import('../pages/SystemPreflightPage').then((module) => ({ default: module.SystemPreflightPage })))
const DemoAdminPage = lazy(() => import('../pages/DemoAdminPage').then((module) => ({ default: module.DemoAdminPage })))
const AuditAdminPage = lazy(() => import('../pages/AuditAdminPage').then((module) => ({ default: module.AuditAdminPage })))

const withSuspense = (component: React.ReactNode) => <Suspense fallback={<LoadingPanel />}>{component}</Suspense>

const rootRoute = createRootRoute({
  component: AuthRoot,
  notFoundComponent: () => <PlaceholderPage title="页面不存在" description="请从左侧导航选择有效模块。" />,
})
const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: '/login', validateSearch: (search: Record<string, unknown>) => ({ returnTo: typeof search.returnTo === 'string' ? search.returnTo : undefined }), component: LoginPage })
const setupRoute = createRoute({ getParentRoute: () => rootRoute, path: '/setup', component: SetupPage })
const dashboardRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: () => withSuspense(<DashboardPage />) })
const incidentStatuses: IncidentStatus[] = ['DETECTED', 'CORRELATING', 'INVESTIGATING', 'DIAGNOSED', 'PLANNING', 'WAITING_APPROVAL', 'REMEDIATING', 'VERIFYING', 'RESOLVED', 'CLOSED', 'OBSERVABILITY_LOST', 'NEEDS_HUMAN', 'MITIGATED_NOT_RESOLVED', 'FAILED', 'CANCELLED']
interface IncidentSearch {
  status?: IncidentStatus
  environment?: string
  q?: string
}
const incidentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/incidents',
  validateSearch: (search: Record<string, unknown>): IncidentSearch => {
    const result: IncidentSearch = {}
    if (incidentStatuses.includes(search.status as IncidentStatus)) result.status = search.status as IncidentStatus
    if (typeof search.environment === 'string' && search.environment.trim()) result.environment = search.environment.trim()
    if (typeof search.q === 'string' && search.q.trim()) result.q = search.q.trim()
    return result
  },
  component: () => withSuspense(<IncidentsPage />),
})
const incidentDetailRoute = createRoute({ getParentRoute: () => rootRoute, path: '/incidents/$incidentId', component: () => withSuspense(<IncidentDetailPage />) })
const incidentEvidenceRoute = createRoute({ getParentRoute: () => rootRoute, path: '/incidents/$incidentId/evidence', component: () => withSuspense(<IncidentEvidencePage />) })
const incidentEvidenceDetailRoute = createRoute({ getParentRoute: () => rootRoute, path: '/incidents/$incidentId/evidence/$evidenceId', component: () => withSuspense(<IncidentEvidenceDetailPage />) })
const actionsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/actions', component: () => <RequireRole role="operator">{withSuspense(<ActionsPage />)}</RequireRole> })
const alertsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/alerts', component: AlertsPage })
const runnersRoute = createRoute({ getParentRoute: () => rootRoute, path: '/runners', component: RunnersPage })
const resourcesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/resources', component: ResourcesPage })
const logsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/logs', component: () => <RequireRole role="operator">{withSuspense(<LogsPage />)}</RequireRole> })
const probesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/probes', component: () => <RequireRole role="operator">{withSuspense(<ProbesPage />)}</RequireRole> })
const prometheusRoute = createRoute({ getParentRoute: () => rootRoute, path: '/metrics', component: () => <RequireRole role="operator">{withSuspense(<PrometheusPage />)}</RequireRole> })
const hostSnapshotsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/host-snapshots', component: () => <RequireRole role="operator">{withSuspense(<HostSnapshotsPage />)}</RequireRole> })
const approvalsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/approvals', component: () => <RequireRole role="operator"><ApprovalsPage /></RequireRole> })

const placeholders = [
  ['/tasks/new', '创建 Agent 任务', '目标澄清、TaskSpec 和计划确认流程将在下一批迁移。'],
] as const

const placeholderRoutes = placeholders.map(([path, title, description]) => createRoute({
  getParentRoute: () => rootRoute,
  path,
  component: () => {
    const page = <PlaceholderPage title={title} description={description} />
    if (path === '/tasks/new') return <RequireRole role="operator">{page}</RequireRole>
    return page
  },
}))
const identityRoute = createRoute({ getParentRoute: () => rootRoute, path: '/identity', component: () => <RequireRole role="admin">{withSuspense(<IdentityAdminPage />)}</RequireRole> })
const outboxRoute = createRoute({ getParentRoute: () => rootRoute, path: '/outbox', component: () => <RequireRole role="admin">{withSuspense(<OutboxAdminPage />)}</RequireRole> })
const policiesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/policies', component: PoliciesPage })
const faultLabRoute = createRoute({ getParentRoute: () => rootRoute, path: '/lab', component: () => <RequireRole role="admin">{withSuspense(<FaultLabPage />)}</RequireRole> })
const systemPreflightRoute = createRoute({ getParentRoute: () => rootRoute, path: '/system/preflight', component: () => <RequireRole role="admin">{withSuspense(<SystemPreflightPage />)}</RequireRole> })
const demoRoute = createRoute({ getParentRoute: () => rootRoute, path: '/demo', component: () => <RequireRole role="admin">{withSuspense(<DemoAdminPage />)}</RequireRole> })
const auditRoute = createRoute({ getParentRoute: () => rootRoute, path: '/audit', component: () => <RequireRole role="admin">{withSuspense(<AuditAdminPage />)}</RequireRole> })
const routeTree = rootRoute.addChildren([loginRoute, setupRoute, dashboardRoute, incidentsRoute, incidentDetailRoute, incidentEvidenceRoute, incidentEvidenceDetailRoute, alertsRoute, resourcesRoute, logsRoute, probesRoute, prometheusRoute, hostSnapshotsRoute, runnersRoute, actionsRoute, approvalsRoute, identityRoute, outboxRoute, policiesRoute, faultLabRoute, systemPreflightRoute, demoRoute, auditRoute, ...placeholderRoutes])

export const router = createRouter({
  routeTree,
  defaultPendingComponent: () => <LoadingPanel />,
  defaultErrorComponent: ({ error }) => <ErrorPanel error={error as Error} />,
  defaultPreload: 'intent',
})

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
