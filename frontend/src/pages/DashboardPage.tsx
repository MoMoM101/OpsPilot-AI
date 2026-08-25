import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { dashboardQuery } from '../api/queries'
import { IncidentStatusBadge, ObservabilityBadge, SeverityBadge } from '../components/StatusBadge'
import { useAuth } from '../auth/AuthContext'

const PendingMetric = () => <small className="pending-metric">暂未接入</small>

export function DashboardPage() {
  const { data } = useSuspenseQuery(dashboardQuery)
  const { canWrite } = useAuth()
  const minutes = Math.floor(data.meanInvestigationSeconds / 60)
  const seconds = data.meanInvestigationSeconds % 60
  return <>
    <section className="page-heading"><div><span className="eyebrow">AGENT OPERATIONS</span><h1>Agent 运行总览</h1><p>查看 Agent 正在处理什么、为何这样判断，以及何时需要人工决策。</p></div>{canWrite && <Link to="/tasks/new" className="primary-button">＋ 创建任务</Link>}</section>
    <section className="command-hero">
      <div className="agent-orb">✦</div><div><span className="live-label"><i />AGENT CONTROL PLANE</span><h2>{data.activeTasks} 个 Agent 正在处置事件</h2><p>{data.activeTasks - data.waitingHuman} 个自主调查 · {data.waitingHuman} 个等待人工 · 运行详情以 Incident 快照为准</p></div>
      <div className="hero-mode"><span>当前策略</span><strong className="pending-value">暂未接入</strong></div>
    </section>
    <section className="metric-grid">
      <article className="metric-card"><span>活跃任务</span><strong>{data.activeTasks}</strong><PendingMetric /></article>
      <article className="metric-card"><span>等待人工</span><strong className="warn-text">{data.waitingHuman}</strong><PendingMetric /></article>
      <article className="metric-card"><span>根因定位率</span><strong className="success-text">{data.rootCauseRate}%</strong><small>后端统计快照</small></article>
      <article className="metric-card"><span>平均调查耗时</span><strong>{minutes}m {seconds}s</strong><small>后端统计快照</small></article>
      <article className="metric-card"><span>Runner 在线</span><strong>{data.runnerOnline}/{data.runnerTotal}</strong><small>当前授权范围</small></article>
    </section>
    <section className="dashboard-grid">
      <div className="panel"><div className="panel-heading"><h2>实时 Agent 任务</h2><Link to="/incidents">全部任务 →</Link></div><div className="task-list">
        {data.incidents.map((incident) => <Link to="/incidents/$incidentId" params={{ incidentId: incident.id }} className="task-row" key={incident.id}><span className={`task-dot ${incident.status.toLowerCase()}`} /><div className="task-copy"><strong>{incident.title}</strong><span>{incident.id} · {incident.resource} · {incident.hypothesis ? `${incident.hypothesis.id} ${incident.hypothesis.confidence}%` : '等待决策'}</span></div><ObservabilityBadge status={incident.observabilityStatus} /><IncidentStatusBadge status={incident.status} /></Link>)}
      </div></div>
      <div className="panel"><div className="panel-heading"><div><h2>运行安全</h2><p>当前用户 Environment 授权范围内的安全快照</p></div><span className="panel-note">API SAFETY</span></div><div className="safety-list"><div><span>需要关注的 Action</span><strong className={data.safety.actionsRequiringAttention ? 'danger-text' : 'success-text'}>{data.safety.actionsRequiringAttention}</strong></div><div><span>其中 UNKNOWN Action</span><strong className={data.safety.unknownActions ? 'warn-text' : undefined}>{data.safety.unknownActions}</strong></div><div><span>待处理审批</span><strong className={data.safety.pendingApprovals ? 'warn-text' : undefined}>{data.safety.pendingApprovals}</strong></div><div><span>活动资源锁</span><strong>{data.safety.activeResourceLocks}</strong></div><div><span>观测丢失 Incident</span><strong className={data.safety.observabilityLostIncidents ? 'danger-text' : undefined}>{data.safety.observabilityLostIncidents}</strong></div></div></div>
    </section>
    <section className="panel"><div className="panel-heading"><h2>活跃 Incident</h2><span className="panel-note">API 快照</span></div><div className="table-wrap"><table><thead><tr><th>ID</th><th>标题</th><th>状态</th><th>观测</th><th>资源</th><th>级别</th><th>负责人</th></tr></thead><tbody>{data.incidents.map((incident) => <tr key={incident.id}><td><Link to="/incidents/$incidentId" params={{ incidentId: incident.id }} className="mono-link">{incident.id}</Link></td><td>{incident.title}</td><td><IncidentStatusBadge status={incident.status} /></td><td><ObservabilityBadge status={incident.observabilityStatus} /></td><td className="mono-cell">{incident.resource}</td><td><SeverityBadge severity={incident.severity} /></td><td>{incident.owner ?? '—'}</td></tr>)}</tbody></table></div></section>
  </>
}
