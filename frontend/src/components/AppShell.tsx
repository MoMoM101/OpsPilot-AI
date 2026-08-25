import { Link, Outlet, useRouterState } from '@tanstack/react-router'
import { useState } from 'react'
import { useIncidentEventStream } from '../api/useIncidentEventStream'
import { dataApi } from '../api/dataApi'
import { IncidentStreamContext } from './IncidentStreamContext'
import { useAuth } from '../auth/AuthContext'

const navigation = [
  { group: 'Agent', items: [{ to: '/', label: '运行总览' }, { to: '/tasks/new', label: '创建 Agent 任务', write: true }, { to: '/incidents', label: 'Incident 列表' }] },
  { group: '可观测性', items: [{ to: '/alerts', label: '告警列表' }, { to: '/resources', label: '资源拓扑' }, { to: '/logs', label: '目标日志查询', write: true }, { to: '/metrics', label: 'Prometheus 查询', write: true }, { to: '/probes', label: '目标健康探测', write: true }, { to: '/host-snapshots', label: '主机快照', write: true }, { to: '/runners', label: 'Runner / Connector' }] },
  { group: '执行与安全', items: [{ to: '/approvals', label: 'Agent 决策审批', write: true }, { to: '/actions', label: '动作执行中心', write: true }, { to: '/lab', label: 'Fault Lab 场景', admin: true }] },
  { group: '治理', items: [{ to: '/policies', label: '策略与自主等级' }, { to: '/identity', label: '身份管理', admin: true }, { to: '/system/preflight', label: '系统部署状态', admin: true }, { to: '/demo', label: 'Demo 数据引导', admin: true }, { to: '/outbox', label: 'Outbox 发布', admin: true }, { to: '/audit', label: '日志与审计', admin: true }] },
]

export function AppShell() {
  const { user, canWrite, isAdmin, logout, refreshSession, sessionExpiresAt } = useAuth()
  const [open, setOpen] = useState(false)
  const [requestedIncidentId, setRequestedIncidentId] = useState<string>()
  const pathname = useRouterState({ select: (routerState) => routerState.location.pathname })
  const incidentMatch = pathname.match(/^\/incidents\/([^/]+)(?:\/evidence(?:\/[^/]+)?)?$/)
  const incidentId = incidentMatch ? decodeURIComponent(incidentMatch[1]) : undefined
  const { state: streamState, connected, lastEventAt } = useIncidentEventStream(incidentId ?? requestedIncidentId)
  const streamLabel = connected ? 'SSE 已连接' : streamState === 'idle' ? 'SSE 未订阅' : streamState === 'connecting' ? 'SSE 连接中' : streamState === 'reconnecting' ? 'SSE 重连中' : streamState === 'authentication_required' ? 'SSE 身份失效' : streamState === 'forbidden' ? 'SSE 无订阅权限' : 'SSE 已断开'
  return <div className="app-shell">
    <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark">✦</div><div><strong>OpsPilot</strong><span>AIOps 控制台</span></div></div>
      <nav aria-label="主导航">
        {navigation.map((section) => <div className="nav-group" key={section.group}>
          <div className="nav-heading">{section.group}</div>
          {section.items.filter((item) => (!('write' in item) || !item.write || canWrite) && (!('admin' in item) || !item.admin || isAdmin)).map((item) => <Link key={item.to} to={item.to} activeProps={{ className: 'nav-active' }} onClick={() => setOpen(false)}>{item.label}</Link>)}
        </div>)}
      </nav>
      <div className="sidebar-footer"><div><span className={`connection-dot ${connected ? '' : 'offline'}`} />{dataApi.mode === 'http' ? 'HTTP API 模式' : 'Mock 数据模式'}</div><div className="identity-summary"><strong>{user?.name}</strong><span>{user?.role} · {user?.unrestrictedEnvironments ? '全部 Environment' : `${user?.environmentIds.length ?? 0} 个 Environment`}</span>{sessionExpiresAt && <span>Session 至 {new Date(sessionExpiresAt).toLocaleTimeString('zh-CN', { hour12: false })}</span>}<div className="identity-actions"><button type="button" onClick={() => void refreshSession()}>刷新会话</button><button type="button" onClick={() => void logout()}>退出登录</button></div></div></div>
    </aside>
    {open && <button className="sidebar-overlay" aria-label="关闭导航" onClick={() => setOpen(false)} />}
    <div className="app-main">
      <header className="topbar">
        <button className="menu-button" aria-label="打开导航" onClick={() => setOpen(true)}>☰</button>
        <div><div className="topbar-title">Incident Control Plane</div><div className="topbar-subtitle">证据驱动 · 有界自治 · 受控执行</div></div>
        <div className="topbar-meta"><span className={connected ? 'stream-connected' : 'stream-offline'}>{streamLabel}</span><span>{lastEventAt ? lastEventAt.toLocaleTimeString('zh-CN', { hour12: false }) : '--:--:--'}</span><span className="environment-chip">{user?.unrestrictedEnvironments ? '全部 Environment' : `受限 ${user?.environmentIds.length ?? 0}`}</span></div>
      </header>
      <main className="page"><IncidentStreamContext.Provider value={{ setRequestedIncidentId }}><Outlet /></IncidentStreamContext.Provider></main>
    </div>
  </div>
}
