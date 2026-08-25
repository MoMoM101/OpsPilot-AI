import { Navigate, Outlet, useRouterState } from '@tanstack/react-router'
import { useAuth } from '../auth/AuthContext'
import { LoadingPanel } from './LoadingPanel'
import { AppShell } from './AppShell'

export function AuthRoot() {
  const { status } = useAuth()
  const location = useRouterState({ select: (state) => state.location })
  const isLogin = location.pathname === '/login'
  const isSetup = location.pathname === '/setup'

  if (isLogin || isSetup) {
    if (status === 'authenticated') {
      const requested = new URLSearchParams(location.searchStr).get('returnTo')
      const destination = requested?.startsWith('/') && !requested.startsWith('//') ? requested : '/'
      return <Navigate to={destination} replace />
    }
    if (status === 'setup_required' && !isSetup) return <Navigate to="/setup" replace />
    if (status === 'unauthenticated' && isSetup) return <Navigate to="/login" search={{ returnTo: undefined }} replace />
    if (status === 'loading') return <LoadingPanel label="检查系统初始化状态" />
    return <Outlet />
  }
  if (status === 'loading') return <LoadingPanel label="初始化用户身份" />
  if (status === 'setup_required') return <Navigate to="/setup" replace />
  if (status === 'unauthenticated') return <Navigate to="/login" search={{ returnTo: `${location.pathname}${location.searchStr}` }} replace />
  return <AppShell />
}

export function RequireRole({ role, children }: { role: 'operator' | 'admin'; children: React.ReactNode }) {
  const { user, canWrite, isAdmin } = useAuth()
  const allowed = role === 'admin' ? isAdmin : canWrite
  if (allowed) return children
  return <section className="panel permission-panel" role="alert"><span className="unavailable-label">PERMISSION DENIED</span><h2>当前角色无权访问此功能</h2><p>{user?.name} 当前为 {user?.role}；该页面需要 {role} 权限。前端限制仅用于改善体验，后端仍会独立校验每个请求。</p></section>
}
